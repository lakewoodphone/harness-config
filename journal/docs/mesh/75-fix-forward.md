# 75 — fix-forward: the two adapter prune scans, and `chat:vscode`

**STREAM S4** of `docs/mesh/71-mesh-program.md` §3. Two jobs, in the order given: the residual
full-table scan in the two adapter prune functions, and the source that had failed 30 times in a row.

Author: delegated agent. Host **ZABZ-YOGA**, 2026-09-16, all times local EDT (= UTC−4).
Repo: `C:\Users\ezabz\code\unified-search`. **Nothing was committed by this agent.** The live index was
never written to and no process was restarted, killed or reconfigured.

Files changed, and only these:

| file | job | what |
|---|---|---|
| `adapters/files/sync.py` | 1 | `prune_docs` deletes through the core's rowid helpers |
| `adapters/journal/sync.py` | 1 | `prune_missing` does the same |
| `adapters/chats/sync.py` | 2 | the DSH corpus is multi-frame zstd; the reader assumed one frame |

`scripts/usearch.py` was **not** touched. Its helpers are called, not reimplemented. While this work
was in progress the parent committed the PART 2 ngram work as **`82c4c26`** ("usearch: the ngram delete
stops scanning the index too", 19:08:04), so `delete_chunks_for_doc`, `delete_ngram_for_doc`,
`ensure_ngram_map` and `SCHEMA_VERSION = 2` are all at HEAD and the calls below resolve against HEAD.

---

# PART 1 — JOB 1: the remaining full-table scan

## 1.1 What was wrong

`docs/mesh/69-read-fix-applied.md` §9.7 named this precisely:

* `adapters/files/sync.py:392` — `DELETE FROM chunks WHERE doc_id=?`, the **1.27 GB full scan per
  vanished file**, plus `:393` for `ngram`;
* `adapters/journal/sync.py:526` — the same two statements.

Both are the un-indexable shape `SCAN chunks VIRTUAL TABLE INDEX 0:` / `SCAN ngram VIRTUAL TABLE
INDEX 0:` — `doc_id` is an UNINDEXED column of an FTS5 table, so deleting **one** document costs the
size of the **whole** table. Confirmed on my own snapshot (EXPLAIN QUERY PLAN, 2026-09-16 19:2x,
`copyA-old.db`):

```
OLD chunks -> SCAN chunks VIRTUAL TABLE INDEX 0:
NEW chunks -> SCAN chunks VIRTUAL TABLE INDEX 0:=          <- rowid EQUALITY
              SEARCH chunks_meta USING COVERING INDEX idx_cm_doc (doc_id=?)
OLD ngram  -> SCAN ngram VIRTUAL TABLE INDEX 0:
NEW ngram  -> needs ngram_meta (absent on this index: schema v1)
```

## 1.2 The change

Both `prune_*` functions now call the core's own helpers, keeping their guards, and delete the map rows
in the same transaction. Two small functions are added to each adapter (identical in shape; twin
comment in each, matching the convention `load_usearch` already set by being duplicated):

```python
def rowid_maps(con) -> set:
    """Which rowid maps this index has, among `chunks_meta` and `ngram_meta`."""
    try:
        return {r[0] for r in con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('chunks_meta','ngram_meta')")}
    except sqlite3.Error:
        return set()


def _delete_doc_rows(con, usearch, oid: int, n_chunks, maps: set) -> None:
    if usearch is not None and "chunks_meta" in maps:
        usearch.delete_chunks_for_doc(con, oid, n_chunks)
    else:
        con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
    if "chunks_meta" in maps:
        con.execute("DELETE FROM chunks_meta WHERE doc_id=?", (oid,))
    if usearch is not None and "ngram_meta" in maps:
        usearch.delete_ngram_for_doc(con, oid)
    else:
        con.execute("DELETE FROM ngram  WHERE doc_id=?", (oid,))
    if "ngram_meta" in maps:
        con.execute("DELETE FROM ngram_meta WHERE doc_id=?", (oid,))
```

and the lookups gain the column the guard needs:

```diff
-            row = con.execute("SELECT id FROM docs WHERE source=? AND external_id=?",
+            row = con.execute("SELECT id, n_chunks FROM docs WHERE source=? AND external_id=?",
                               (source, ext_id)).fetchone()
             if not row:
                 continue
             oid = row["id"]
-            con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
-            con.execute("DELETE FROM ngram  WHERE doc_id=?", (oid,))
+            _delete_doc_rows(con, usearch, oid, row["n_chunks"], maps)
             con.execute("DELETE FROM docs   WHERE id=?", (oid,))
```

```diff
-    gone = [r[0] for r in con.execute("SELECT id, external_id FROM docs WHERE source=?",
-                                      (source,)) if r[1] not in seen]
+    gone = [(r[0], r[2]) for r in
+            con.execute("SELECT id, external_id, n_chunks FROM docs WHERE source=?",
+                        (source,)) if r[1] not in seen]
 ...
-        for oid in gone:
-            con.execute("DELETE FROM chunks WHERE doc_id=?", (oid,))
-            con.execute("DELETE FROM ngram  WHERE doc_id=?", (oid,))
+        for oid, n_chunks in gone:
+            _delete_doc_rows(con, usearch, oid, n_chunks, maps)
             con.execute("DELETE FROM docs   WHERE id=?", (oid,))
```

Each `prune_*` takes the loaded core module as a new trailing argument (`usearch=None`), supplied by the
existing call site: `prune_docs(con, opts.source, gone, usearch)` in `files/sync.py` (the name is already
bound on **both** branches of the call — `load_usearch()` at `:621` for `--direct`, and `:735` for the
JSONL path) and `prune_missing(con, SOURCE, seen, a.verbose, us)` in `journal/sync.py` (that path only
runs under `--direct`, where `us` was already loaded at `:711`).

**The guards are the core's and they are kept.** `delete_chunks_for_doc(con, doc_id, n_chunks)` compares
what it actually deleted against the document's recorded chunk count and falls back to the un-indexable
statement on any disagreement; `delete_ngram_for_doc` compares against the map's own count. Both were
exercised below. `n_chunks` had to travel with the id for that comparison to be possible — that is the
only reason the lookups changed.

**Why the map DELETE is not conditional on the helper.** The first version put
`DELETE FROM chunks_meta` inside the `if usearch is not None and "chunks_meta" in maps:` branch, so an
index with the map but no core module left orphan map rows behind. The guard-and-invariant test caught it
(`orphan_chunks_meta = 4`), and it is fixed: the map is deleted whenever the map exists, however the rows
were removed.

**An index with neither map still prunes.** `rowid_maps` answers from `sqlite_master`, never by
assumption, and each missing map falls back to exactly the statement that ran before. So the change is
strictly monotone: an old index behaves as it did, an index with the maps gets the lookup.

## 1.3 Method — a copy, and read bytes of a process

Follows doc 69 §9.1/§9.3 exactly, because both of its warnings were real:

* **Snapshot with `VACUUM INTO` over a read-only connection**, not a raw file copy. Used here:
  `snapshot.py`, 2,334,269,440 B in **69.5 s**, `PRAGMA quick_check(1)` = **ok in 65.2 s**, taken
  **2026-09-16 ≈19:11 local**. Counts: `docs` 159,600 / `chunks_meta` 988,602 / `ngram` 159,600 /
  `ngram_docsize` 159,600, `schema_version` **1**, `ngram_meta` **MISSING**. Those match doc 69's live
  read-only numbers (159,600 at 19:03:35), so the snapshot is the live index as of that minute.
  Two working copies (`copyA` = old code, `copyB` = new code) were raw copies *of the snapshot* — a
  static file, no writer — verified at 159,600 docs / 988,602 `chunks_meta` each.
* **Read bytes of the process, not a single-document timing.** `GetProcessIoCounters`
  `ReadTransferCount`, sampled around the `prune` call, one process per (mode, N), with an `N=0` floor.
  The counter counts bytes returned by `ReadFile`, so cache-served reads are counted too — which is why
  it is stable while wall clock is not (§1.4).
* **The counter is verified before it is trusted.** The first attempt returned **0 B for everything**,
  because `GetProcessIoCounters` had no `argtypes`: with ctypes' default `restype` of `c_int`, the 64-bit
  process pseudo-handle arrives as `0x00000000FFFFFFFF`, the call fails with `ERROR_INVALID_HANDLE`, and
  the struct stays zeroed — a reading that looks exactly like "no I/O at all". `bench.py` now declares
  `argtypes`/`restype` and runs a `selftest()` that reads a known file and refuses to report if the
  counter cannot see it (`read 1,212,600 B … counter says 1,212,600 B`).
* `old` executes the prune function **verbatim from git HEAD** (`git show HEAD:adapters/<a>/sync.py`,
  the function extracted with `ast` and exec'd); `new` calls the working-tree function. Same statements,
  same data order, same source, same N.

## 1.4 Measured — before and after

Same 3 documents per run, same copy contents, warm cache, 2026-09-16 19:20–19:5x.

| adapter / source | mode | prune wall | **read bytes, 3 docs** | **read B / doc (raw)** | read B / doc, floor subtracted |
|---|---|---|---|---|---|
| `files/sync.py`, `files:yoga` | OLD (copyA) | **146.531 s** | 4,387,163,698 | **1,462,387,899** | 1,462,376,846 |
| `files/sync.py`, `files:yoga` | OLD (copyA), 2nd | 12.369 s | 4,386,926,130 | **1,462,308,710** | 1,462,297,657 |
| `files/sync.py`, `files:yoga` | NEW (copyB) | **0.030 s** | 1,988,840 | **662,947** | 311,400 |
| `files/sync.py`, `files:yoga` | NEW (copyB), 2nd | 0.007 s | 2,013,416 | **671,139** | 319,592 |
| `journal/sync.py`, `journal` | OLD (copyA) | **109.934 s** | 4,387,096,040 | **1,462,365,347** | 1,462,346,809 |
| `journal/sync.py`, `journal` | OLD (copyA), 2nd | 14.131 s | 4,387,034,600 | **1,462,344,867** | 1,462,326,329 |
| `journal/sync.py`, `journal` | NEW (copyB) | **0.032 s** | 808,618 | **269,539** | 133,803 |
| `journal/sync.py`, `journal` | NEW (copyB), 2nd | 0.006 s | 775,850 | **258,617** | 122,880 |

Floors (`N=0`, same process path): OLD 33,160 B (`files`) / 55,614 B (`journal`); NEW 1,054,641 B
(`files`) / 407,210 B (`journal`) — the new floor is `rowid_maps` reading `sqlite_master`.

**Net reduction: 4,696× (`files:yoga`) and 10,929× (`journal`) per pruned document**, floor-subtracted;
2,206× and 5,426× if you take the raw figures and do not subtract. Wall clock for the same 3 documents:
146.5 s → 0.030 s and 109.9 s → 0.032 s.

Two things deliberately not hidden:

* **The wall clock is not a trustworthy measure here and the byte count is.** The two OLD runs are the
  same work: 146.5 s and 12.4 s (12× apart) at 4,387,163,698 B and 4,386,926,130 B (0.005 % apart).
  Doc 69 saw the same 2× cache sensitivity. The bytes are what the fix changes; the seconds are cache.
* **The residual 0.26–0.67 MB per document is real and is not a scan.** It is the FTS5 delete's own
  index maintenance plus the map lookups: reading the segment pages a delete must rewrite. It is ~2,100×
  below the 1.27 GB it replaces, and it scales with the deleted document's chunk count, not the corpus.
  `files:yoga` documents average 9.6 chunks and cost 0.66 MB; `journal` documents average 1.9 chunks and
  cost 0.27 MB. That ordering is what you expect if the remaining cost is per-chunk FTS5 work.

`init_db` is a once-per-process cost and is unchanged by this work: **28,143,632 B** on a cold copy
(31,891,456 B on later runs) — the `ensure_ngram_map` counting pass doc 69 §9.3 measured at ~33 MB. It is
paid identically by both modes, so it cancels in the table above; it is not part of the prune.

## 1.5 The guards, exercised through the real code path

`guard_test.py` builds its own small index (never `~/.usearch`) and drives the **real** `prune_docs` /
`prune_missing`, then asserts five invariants. All checks pass.

| case | what was injected | result |
|---|---|---|
| normal | nothing | helpers used, **no fallback**, doc + all four row sets gone, all invariants 0 |
| chunks map stale | one `chunks_meta` row deleted | `usearch: doc 1: 3 chunk row(s) deleted through chunks_meta but n_chunks=4; falling back to the full-scan delete so none is left behind` — invariants 0 |
| ngram map stale | the `ngram_meta` row deleted | `usearch: doc 1: 0 ngram row(s) deleted through ngram_meta but the map records 0; falling back…` — invariants 0 |
| no maps at all | `chunks_meta` and `ngram_meta` dropped | no crash, plain statements run, doc gone, `orphan_chunks` 0 |
| no core module | `usearch=None` | no crash, plain statements run, doc gone, `orphan_chunks` and `orphan_chunks_meta` 0 |

Invariants asserted after every case: `orphan_chunks`, `chunks_without_meta`, `orphan_chunks_meta`,
`ngram_without_meta`, `orphan_ngram` — all **0**.

## 1.6 Suite

`python -m pytest tests/ -q` with `PYTHONDONTWRITEBYTECODE=1`: **458 passed, 1 skipped, 71 subtests
passed** in 232.5 s, after all three edits. `ast.parse` OK on all three files.

## 1.7 What this buys, and what it does not

* **Chunks — live now.** `chunks_meta` exists on the live index (988,602 rows), so the 1.27 GB-per-
  vanished-document scan is gone from both prune paths as soon as the next adapter run loads this code.
  Both adapters spawn fresh processes per run, so no restart is needed.
* **ngram — armed, not yet firing.** `ngram_meta` does **not** exist on the live index: measured
  read-only at **23:42:02Z**, `schema_version` = **1**, `ngram_meta` **absent**. The reason is in §3
  item 2: the only live writer loaded pre-`82c4c26` code. The moment any new `usearch.py add` runs, `init_db` →
  `ensure_ngram_map` creates and fills the map (the 28 MB one-time adoption measured in §1.4), and
  `rowid_maps` will then report it and the ngram fast path turns itself on with **no further change**.
  I did not make the adapters create the schema: creating tables is the writer's job, every writer path
  already does it, and `rowid_maps` is honest about the state it finds.
* **Still scanning nothing else here.** The adapters' cost is proportional to the number of documents
  that vanish per run, not to the corpus, so this was never the dominant amplifier — it was the last
  un-indexable statement in the ingest path. Doc 68/69 §5's other items are untouched by this change:
  `--direct` state that is only saved at the end of a run, the decorative `timeout_seconds` on some
  paths, and the 30-minute cadence over a source that needs longer.

---

# PART 2 — JOB 2: `chat:vscode` failing 30 times in a row

## 2.1 What the state and the log said

`~/.usearch/state/sync.json` (4,839 B, mtime **18:46:20** — the run state, distinct from the adapter's
own `state/chats.json`, which is 523,448 B at the same mtime), entry `chat:vscode`:

```
consecutive_failures 30   runs 30   checks 0   docs_read 0   docs_written 0
last_success null         last_failure 2026-09-16T22:46:20Z   duration_seconds 1.97
last_exit 1               mode stdout   adapter adapters/chats/sync.py   args --source all
last_error  "adapter exited 1: chats: {"sources": {"vscode": {…"files_read": 0, "sessions": 0, …
             "copilot-cli": {"source": "copilot-cli", "files_seen": 2154, "files_skipped_unchanged":
```

`~/.usearch/logs/sync.log` carries the same line repeated for every run, cut at 400 characters by
`oc.last_meaningful_line(err_text, 400)`. **Neither the log nor the state contains the reason** — both
truncate exactly before it. That is why this needed reproducing rather than reading.

## 2.2 Reproduced, in the runner's own environment

`sync.py` spawns the adapter with `PYTHONIOENCODING=utf-8` and a UTF-8 pipe (`adapter_env`), so the
reproduction must too. Run with `--state` pointing at a **copy** of `chats.json`, so the real state is
never written:

```
python adapters/chats/sync.py --source all --state <copy> --out -
exit=1  seconds=3.04  stdout_bytes=0
chats: {"sources": {…
  "vscode":      files_seen 285,  files_skipped_unchanged 285,  files_read 0, sessions 0, failures 0,
  "copilot-cli": files_seen 2154, files_skipped_unchanged 2154, files_read 0, sessions 0, failures 0,
  "dsh":         files_seen 458,  files_skipped_unchanged 444,  files_read 14, sessions 0,
                 empty_sessions 7, failures 7,
                 "notes": {"retryable": 7,
                           "zstd stream error: cannot use a decompressobj multiple times": 7}}}
```

**The failing source is `dsh`, not `vscode`.** The registry source named `chat:vscode` runs
`adapters/chats/sync.py --source all`, which reads all three corpora; `hard_fail` in `main()` is
`y.failures and y.sessions == 0 and y.files_read > 0`, and only `dsh` satisfies it — so the whole source,
and its 30-run counter, is failed by the DSH corpus.

(A first reproduction without `PYTHONIOENCODING` died with a `UnicodeEncodeError` on `\u2705` writing to
a cp1252 redirect. That is **not** the production failure — the runner sets UTF-8 — and is recorded here
only so the wrong cause is not adopted later.)

## 2.3 The cause

**A DSH session file is a concatenation of zstd frames, and the reader assumed one frame.**

* 7 files over 4 MiB, 7 failures. The adapter reads in `1 << 22` = 4 MiB chunks.
* `zstandard` **0.25.0**; `ZstdDecompressor.decompressobj()` defaults to **`read_across_frames=False`**,
  documented in the installed library itself (`backend_cffi.py:3926-3928`): *"If False, reading stops
  after 1 frame and subsequent decompress attempts will raise an exception."*
* The raise is `backend_cffi.py:2964-2965`:
  ```python
  if self._finished:
      raise ZstdError("cannot use a decompressobj multiple times")
  ```
  and `self._finished` is set at `:3002-3008` the moment a frame is fully decoded (`zresult == 0`).
* The first frame is ~200 bytes — the `{"type":"session",…}` header — so it always ends inside the
  first read chunk. On the **second** `fh.read()`, the object is spent and raises.

Measured on that host, 2026-09-16, per file:

| file | size | frame 1 ends within | `read_across_frames=True` | `read_across_frames=False` (what the adapter produced) |
|---|---|---|---|---|
| `session-0898187e-…` | 6,675,735 B | 65,536 B | 23,311,554 B | **198 B** |
| `session-3ca4f3f2-…` | 5,811,276 B | 65,536 B | 21,428,028 B | **198 B** |
| `session-4db964fb-…` | 5,560,664 B | 65,536 B | 21,065,685 B | **198 B** |
| `session-85f98648-…` | 9,453,098 B | 65,536 B | 33,640,298 B | **198 B** |
| `session-87dce8c8-…` | 4,550,756 B | 65,536 B | 16,528,520 B | **198 B** |
| `session-b60e96b3-…` | 12,838,292 B | 65,536 B | 48,568,009 B | **198 B** |
| `session-e34dd061-…` | 5,452,617 B | 65,536 B | 19,291,300 B | **198 B** |

Frames per file, measured: a 400-byte session holds **3**; a 386 KB session 67–184; the 5.7 MB session
**2,108**; the 12.8 MB session **5,709**. One frame per flush, which is exactly what the harness does.

## 2.4 The half that was not failing at all

The 7 oversized files raised and were reported. Every file **under** 4 MiB did something worse: the
single `fh.read()` returned the whole file, `decompress()` consumed frame 1 and stopped, `fh.read()`
then returned `b""`, the loop ended, `obj.eof` was **True** — so `complete = True`, `retryable = False`,
no failure, and the session produced no messages. `run_source` then wrote it into the state as read:

```python
if doc is None:
    y.empty_sessions += 1
    state.note(path, st.st_size, st.st_mtime_ns, 0)     # docs: 0 -> never re-read
```

Measured on six real sub-4 MiB sessions: **198 of 534 bytes returned (37.1 %), retryable = 0.** Across
the whole corpus, the old reader returned **122,895 bytes** of the **1,032,257,610 bytes** those files
hold — **0.01 %** — retryable on 7 files only. And the live state agrees: of 447 `…\.dsh\…` entries in
`~/.usearch/state/chats.json`, **447 have `docs: 0`**, and the index snapshot contains
**0 documents for `chat:dsh`** (only `chat:vscode`, 2,418). The DSH corpus was never indexed.

This is the reason the fix could not stop at the decompression: **a fix that only stops the exception
would make the source exit 0 while leaving 447 sessions marked "read, nothing to index".** A green
counter over an empty corpus is the exact failure this fleet's own history is made of.

## 2.5 The fix

**`dsh_read_events` walks frames by hand.** Each frame gets its own decompress object; `obj.unused_data`
returns the bytes after the frame that just finished, and those go to a fresh object. Truncation is still
detected, now as "the last frame we started never finished" instead of "the first frame finished", which
keeps the property the function exists for:

```python
                    pending = chunk
                    while pending:
                        buf.extend(obj.decompress(pending))
                        ...drain whole lines...
                        if obj.eof:
                            last_frame_finished = True
                            pending = obj.unused_data
                            obj = zstd.ZstdDecompressor().decompressobj()
                        else:
                            last_frame_finished = False
                            pending = b""
...
            if not last_frame_finished:
                yield b"", True, "incomplete zstd frame (file may still be growing)"
```

The first written version used `while pending: … else:` and reset the flag on the last iteration — the
verification below caught it before the edit was made (`all_seven_match=False`, 461/461 files reported
retryable). The construct in the file is the second version, which was verified first.

**A per-source parser generation invalidates the state for the corpus whose parser changed.** Raising
`PARSER_VERSION` would invalidate all three corpora at once, and the VS Code corpus alone is 4.04 GB with
a single 289 MB line against this source's 900 s timeout — a global bump is how a correct fix turns into
a timeout. So:

```python
PARSER_GENERATIONS = {"dsh": 2}
def parser_generation(source: str) -> int:
    return PARSER_GENERATIONS.get(source, PARSER_VERSION)
```

and `State.unchanged`/`State.note` take the source and compare against it. The dsh entries written under
generation 1 are re-read; the 2,416 VS Code and Copilot entries stay valid. This is the mechanism the
class docstring already described for exactly this situation ("an improved parser re-reads rather than
leaving stale extractions behind"), scoped to the corpus that changed.

## 2.6 Verified after

Same command, same state copy, `--out <temp file>`:

```
exit=0   seconds=137.5   jsonl_bytes=58,289,145
  "vscode":      files_seen 285,  files_skipped_unchanged 285,  files_read 0, sessions 0, failures 0,
  "copilot-cli": files_seen 2154, files_skipped_unchanged 2154, files_read 0, sessions 0, failures 0,
  "dsh":         files_seen 471,  files_skipped_unchanged 0,    files_read 471, sessions 457,
                 empty_sessions 14, messages 12,033, text_bytes 56,546,023,
                 partial 0, failures 0, notes {}
  documents_emitted 457
```

* **exit 1 → exit 0**, and `hard_fail` is now empty on its own terms rather than by suppression.
* **457 sessions, 12,033 messages, 56.5 MB of transcript** recovered — the content §2.4 shows was being
  thrown away and then marked as read.
* **137.5 s against the source's 900 s timeout**, so the one-time re-read fits.
* **VS Code and Copilot were not re-read** (`files_read 0`), which is the per-source generation doing
  what it is for.
* Correctness against an independent answer: the frame-walking reader's output is byte-exact with
  `decompressobj(read_across_frames=True)` on all 7 oversized files, and the retryable count over the
  whole corpus is **0**.
* The synthetic cases that guard the old behaviour still behave: `single_frame` retryable=0,
  `two_frames` retryable=0, `two_frames_plus_partial` **retryable=1**, `not_zstd` retryable=1,
  `truncated_single` retryable=1.
* `python -m pytest tests/test_chats_adapter.py -q` → **30 passed**; all `tests/` → **458 passed,
  1 skipped**.

## 2.7 What was not done

* The live `~/.usearch/state/chats.json` was **not** written, moved, deleted or rebuilt. It is at
  **523,448 B, mtime 18:46:20**, the same as before this session started, and the reproduction used a
  copy passed via `--state`. The counters still read 30/0 — deliberately. They will move on the next
  real run, and the honest way for them to move is by the source succeeding.
* Nothing was run against the live index. The adapter runs above wrote to a temp JSONL file, never to
  `~/.usearch/usearch.db`.

---

# 3. What I could not verify

1. **The first post-fix live tick.** It is scheduled for `19:45:46` (`LastRunTime 19:15:47`,
   `LastTaskResult 267014` = terminated). The 18:45 run is **still alive**: `sync.py` PID 14952 (18:45:47)
   and its `db:localdb` child `usearch.py add` **PID 8940**, started **18:46:20**, holding the write
   lock. So the same collision doc 68 §2 / doc 69 §9.8 describe can still make the next tick fail with
   `database is locked` before either fix is reached. I did not kill it — the brief forbids it, and it
   would have been the wrong thing to do to a writer I did not start.
   *Consequence for my change*: the chunks fast path is on disk and will be loaded by the next adapter
   process, but the first run that can demonstrate it end-to-end is the first one that gets the lock.
2. **The ngram fast path against the live index.** `ngram_meta` does not exist there (read-only at
   **23:42:02Z**: `schema_version` 1, table absent), because the only live writer — PID 8940 — loaded
   `usearch.py` before `82c4c26`. Verified instead on the copy (§1.4, §1.5), where `init_db` created and
   filled the map and both helpers ran. The prediction is that the map appears with the next new
   `usearch.py add`; I did not observe it appear.
3. **`fts_integrity_rank` on the live index.** Its probe needs the write lock (doc 69 §5.3), which the
   wedged ingest holds. Not attempted, per the brief. Everything else in `integrity_check` was run
   against the copy and through the adapter paths in §1.5 with the same SQL.
4. **The end-to-end prune inside a real `files:local` / `journal` run.** The prune functions were driven
   directly with real ids from the real index (§1.4), and both adapter test suites pass, but I did not
   let a full scheduled run reach the prune step — `files:local` exits 3 today for an unrelated reason
   (`adapter exited 3`, 43.88 s, 65 docs) and the lock is held.
5. **Whether `chat:dsh` reaches a stable 457 documents on the live index.** The recovery is measured as
   JSONL output (457 docs, 58.3 MB), not as ingested rows: the ingest cannot take the write lock right
   now. The document count will also drift upward as live sessions gain messages.
6. **The absolute `ReadTransferCount` of any live process.** Readings of a long-lived process were
   already non-monotonic in doc 69 §6.5; I report only per-process deltas around a known call on a copy,
   which is what makes §1.4 reproducible.

---

# 4. Provenance

Everything above was produced on **ZABZ-YOGA** on **2026-09-16 between 19:08 and 19:55 local**, by the
commands and code shown.

**Live-index facts** came from **read-only** connections only (`file:...?mode=ro`): the index snapshot
source (`VACUUM INTO`, which writes to the *destination*, never the source), the column survey, the
EXPLAIN QUERY PLANs, and the 23:42:02Z `ngram_meta` check. `~/.usearch/usearch.db` moved during the
session — doc 69 §9.9 recorded 2,366,541,824 B at 19:05:30 and I measured 2,370,965,504 B at 19:38:46 —
which is PID 8940's own checkpointing, not mine.

**The snapshot** `%TEMP%\zabz-s4\usearch.db` was taken by `snapshot.py` at **≈19:11** (2,334,269,440 B,
`quick_check` ok in 65.2 s, counts matching doc 69's 19:03:35 live read). Its two working copies
`copyA-old.db` / `copyB-new.db` are raw copies of that static file. `bench.py` verifies its I/O counter
before each measurement. All of it is under `%TEMP%`; nothing was left in the repo and
`git status --porcelain` showed `M adapters/chats/sync.py`, `M adapters/files/sync.py`,
`M adapters/journal/sync.py` and nothing else — the scratch scripts live in
`%TEMP%\zabz-s4\` (`snapshot.py`, `bench.py`, `guard_test.py`, `verify_fix.py`, `probe_dsh.py`,
`probe_old_vs_new.py`, `chat_counts.py`, plus `*_HEAD.py` extracts from `git show`).

The three large database files — the snapshot and its two working copies, 6.53 GiB — were **deleted at
19:56**, confirmed absent (`0 .db file(s)` in that directory; free space 63.4 → 69.9 GiB). The scripts,
both measurement logs, the reproduced pre-fix and post-fix adapter stderr, and the 58,289,145-byte
post-fix JSONL were kept as evidence. `snapshot.py` re-takes a trustworthy snapshot in 69.5 s if any of
§1.4 needs reproducing.

**No write of any kind was made to `C:\Users\ezabz\.usearch\`.** `state/chats.json` is untouched at its
18:46:20 mtime; the only adapter runs used `--state` copies and `--out` temp files.

**No commit.** `scripts/usearch.py` was not touched; `82c4c26` was made by the parent at 19:08:04 while
this work was in progress, and every call in this change resolves against it.
