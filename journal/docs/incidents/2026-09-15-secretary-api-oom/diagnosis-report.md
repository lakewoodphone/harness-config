# API OOM — Evidence Report (final revision)

**Host:** `secratary` (Linux 7.0.0-30-generic, 4 CPUs, 23,984,072 kB RAM, 4,194,300 kB swap)
**Unit:** `secretary-api.service` — `uvicorn app.main:app --host 0.0.0.0 --port 8002`
**Code root:** `/home/zabz/personal-secretary-mvp` (Python 3.14.4 venv, SQLite 3.46.1)
**Observed live:** 2026-09-15 23:10 → 23:41 UTC, **READ-ONLY**
**PIDs:** 364647 (→OOM 23:19:18) · 379293 (→23:28:08) · 383209 (→**OOM 23:34:43**) · 393290 (→**SEGV 23:37:43**) · 404363 (23:38:07 →)

---

## 0. Headline — the runaway is (so far) **stopped** by the two deployed commits, and my own leading suspect was **wrong**

**[OBSERVED] Current state — the single most important fact in this report.** With `44e3f8e8`
(8 MB cache, `temp_store=FILE`) **and** `ce20ab28` (single-flight, 10 s-cached `/health` probe) both
live, the process has been **flat for 10+ minutes and has not died**:

```
23:39:42  pid=404363  RSS   803 MB
23:40:57  pid=404363  RSS 1,668 MB      <- warmed up over ~2.5 min
23:42:09  pid=404363  RSS 1,773 MB
23:44:31  pid=404363  RSS 1,802 MB
23:46:54  pid=404363  RSS 1,813 MB      <- FLAT
23:48:08  pid=404363  RSS 1,814 MB
23:50:30  pid=404363  RSS 1,801 MB
23:50:52  pid=404363  RSS 1,850 MB   at 13 min 18 s uptime, 42 handles on secretary.db, 45 threads,
                                     7 rw-anon maps >=56 MB (1,177 MB) — all CONSTANT for 10 minutes
                                     0 oom-kill and 0 core-dump since 23:38
```
For comparison: with `44e3f8e8` alone the previous process (383209) was OOM-killed at **6 min 35 s** and
19.0 GB; pre-fix runs died at 15 and 54 minutes.

**What this means — and it corrects my own earlier claim in this same report.** The mechanism was the
one py-spy showed directly at 23:11:57 (§4.4): a probe storm manufacturing a thread per request, each
thread taking its **own per-thread SQLite connection**, each connection carrying a large page cache —
with thread and connection counts *climbing*, so the product `threads × cache_size` was unbounded.
Pre-fix that was 64 MB × 60–85+ connections and rising; `44e3f8e8` cut the multiplier 8×, and
`ce20ab28` removed the storm. Together they stopped it.

**I was wrong to promote the ChromaDB / Rust layer to "leading suspect".** My reasoning was that
`Sep 15 23:34:42 kernel: tokio-rt-worker invoked oom-killer` implicated a Rust allocator. **That
inference does not hold:** when the system is already out of memory, the OOM killer names whichever
thread *happened to request the next page* — it says nothing about which thread allocated the previous
18 GB. `tokio-rt-worker` was the trigger, not the cause. Likewise the `11/SEGV` four minutes later
(§1) is best read as a downstream native failure in an OOM-exhausted process, not as proof of a Rust
allocator bug. **ChromaDB is demoted in §5 and should not be chased on this evidence.**

My earlier hypothesis "the burst is `cache_size=-64000` × one connection per thread" was **partly
right and partly wrong**, and the distinction is the whole lesson: the *page-cache size* was
falsified as sufficient on its own (`44e3f8e8` alone still died at 6m35s), while the *thread/
connection storm multiplying it* was the actual driver — and that is what `ce20ab28` removed.

| # | Claim | How it was tested in production | Verdict |
|---|---|---|---|
| 1 | Burst = 64 MB page cache × one connection per thread | `44e3f8e8` alone deployed 23:22:20 | **Partially falsified.** Still OOM'd at 23:34:43, 19.0 GB, 6m35s — the cache size alone was not enough |
| 2 | Burst = **thread/connection storm** multiplying that cache | `ce20ab28` (probe storm removed) added on top of #1, 23:38 | **SUPPORTED.** Flat at ~1.8 GB for 10+ min, handles constant at 42, zero kills |
| 3 | Burst = a raw `sqlite3.connect()` outside `_get_conn` | 40+ call sites audited; library defaults measured; a 200k-row sort run | **FALSIFIED.** Defaults `cache_size=-2000`, `temp_store=0`; the sort moved RSS by **4 MB** and spilled to a file |
| 4 | Burst = ChromaDB / Rust vector layer | `tokio-rt-worker invoked oom-killer` + a later SEGV | **RETRACTED.** The oom-killer line names the thread that *triggered* the kill, not the allocator |

**Caveat before anyone declares victory: 13 minutes of stability is strong but not conclusive.** One
pre-fix run survived **62 minutes** before dying, and the burst window I measured was 13–15 minutes on
two occasions but 54–62 minutes on others. **A ≥60-minute soak with RSS flat is the real test** — and
`ce20ab28` landed only 13 minutes before this report, so nobody has seen that window yet.

**[OBSERVED] Still outstanding:** the steady state is now **~1.8 GB**, roughly **2× the pre-fix flat
baseline of ~0.9 GB**, with a constant 42 handles. That is stable, not climbing, and 10× below the
kill threshold — but it is a change worth watching, and the residual thread/connection manufacturing
in §4.5 has still not been attributed.

**Constraints honoured:** nothing restarted, stopped or edited by me; no service, SQLite file, venv or
repo file modified; the app was never run; patch produced by editing **copies** and verified with
`git apply --check`, which does not write.

> **Label convention:** **[OBSERVED]** = raw output I captured. **[INFERRED]** = reasoning plus the
> test that would confirm or falsify it. **UNKNOWN** = not determined.

---

## 1. The kills — eight OOMs and one segfault

**[OBSERVED]** `journalctl`, `Out of memory: Killed process …`, 2026-09-15:

| # | kernel time | pid | total-vm | **anon-rss** | uptime | note |
|---|---|---|---|---|---|---|
| 1 | 13:34:33 | 3985542 | 26,469,576 kB | 21,983,740 kB | — | `wf-tick_0` invoked the killer |
| 2 | 20:12:14 | 183696 | 24,754,244 kB | 20,271,732 kB | — | |
| 3 | 20:41:04 | 248840 | 24,014,500 kB | 19,984,780 kB | — | |
| 4 | 21:01:35 | 268781 | 24,026,396 kB | 19,967,464 kB | — | |
| 5 | 22:06:31 | 275330 | 25,165,664 kB | 20,207,184 kB | 62 min | |
| 6 | 23:00:46 | 306180 | 25,570,188 kB | 20,253,756 kB | 54 min | |
| 7 | 23:19:18 | 364647 | — | `19.2G peak` | 15 min | pre-fix |
| **8** | **23:34:43** | **383209** | **22,748,056 kB** | **19,937,288 kB** | **6 min 35 s** | **POST-fix `44e3f8e8`; `tokio-rt-worker` invoked the killer** |
| — | 23:37:43 | 393290 | — | `3.2G peak` | 2 min 59 s | **native crash, `status=11/SEGV`, core-dump** |

Only six were in the brief. Every OOM was a **global** OOM with no cgroup constraint:

```
Sep 15 23:34:43 kernel: oom-kill:constraint=CONSTRAINT_NONE,nodemask=(null),cpuset=/,mems_allowed=0,
                            global_oom,task_memcg=/system.slice/secretary-api.service,task=python,pid=383209,uid=1000
```

**[OBSERVED]** At the 23:00:46 kill the kernel's per-task table showed the API at **84 % of all
anonymous memory**, nothing else comparable — not a noisy-neighbour problem:

```
[  pid  ]   uid  tgid total_vm      rss rss_anon rss_file ... name
[ 306180]  1000 306180  6392547  5064110  5063439      671 ... python       <- the API: 19.3 GB
[3465602]  1000 3465602  5835334   138508   137798      675 ... node         <- dashboard: 529 MB
   … every other process ≤ 530 MB …
```

**[OBSERVED]** No memory ceiling on the unit, so the *host* gets protected and the API is SIGKILLed
undrained; swap was fully consumed (`Free swap = 184kB` of `4,194,300 kB`):

```
$ systemctl show secretary-api -p MemoryMax -p MemoryHigh -p MemorySwapMax
MemoryMax=infinity / MemoryHigh=infinity / MemorySwapMax=infinity
```

---

## 2. The growth curve — flat, then ~18 GB inside ~35 s

**[OBSERVED]** Pre-fix, `VmRSS` of 364647 (`oom-evidence/rss-samples.tsv`, `counter.tsv`):

| wall (UTC) | uptime | RSS | note |
|---|---|---|---|
| 23:10:46 | 6:28 | 875,692 kB (0.84 GB) | plateau |
| 23:13:06 | 8:48 | 898,988 kB (0.86 GB) | **flat after 9 minutes** |
| 23:17:28 | 13:09 | 2,530,396 kB (2.41 GB) | runaway begun |
| 23:18:45 | 14:26 | 3,500,520 kB (3.34 GB) | **+961 MB in 20 s** |
| 23:19:06 | 14:47 | 12,472,008 kB (11.89 GB) | **+8.97 GB in 21 s** |
| 23:19:18 | 14:59 | killed | 19.2 GB peak |

**[OBSERVED]** Post-fix, independently sampled by the orchestrator on 383209 — the same shape, and the
rate is why a 30 s sampler mostly misses it:

```
RSS 743 MB -> 1071 MB -> 1600 MB      DB handles 13 -> 85      threads 34 -> 58
…then the process vanished (OOM), i.e. the remaining ~17-18 GB landed inside a ~35 s band.
```

**Conclusions:** the process does **not** leak at idle (flat for 9–13 min); this is a **triggered
burst**. "5–10 MB/s" is a lifetime average — the instantaneous rate is **~430 MB/s**, which is one or
a few enormous allocations, not small-object accumulation. **And `temp_store=FILE` changed none of
this.**

---

## 3. Where the memory is — mapping-level attribution

**[OBSERVED]** Parsing `/proc/<pid>/smaps` for every read-write anonymous mapping (`counter.py`):

| wall (UTC) | RSS total | rw-anon maps ≥56 MB | RSS inside them | share | **largest single map** |
|---|---|---|---|---|---|
| 23:12:33 | 877 MB | 3 (two exactly **64 MB**) | ~190 MB | 22 % | — |
| 23:16:06 | 1,948 MB | 44 maps ≥32 MB (3,776 MB virtual) | 1,573 MB | 81 % | — |
| 23:17:28 | 2,530 MB | **18** | **1,810 MB** | **72 %** | 697 MB |
| 23:18:45 | 3,341 MB | 18 | 2,772 MB | **83 %** | 958 MB |
| 23:19:06 | **12,176 MB** | 19 | **11,574 MB** | **95 %** | **7,393 MB** |

**1 : 1 attribution** — 23:18:45 → 23:19:06:

```
rss_total   +8,971,488 kB   (+8.56 GiB)
rss_ge56MB  +8,802 MB       (+8.60 GiB)   = 98.1% of the increment
maps_ge56MB  18 -> 19        (one new mapping)
rss_top1_MB  958 -> 7,393    (that ONE mapping grew by 6.4 GiB)
```

**[OBSERVED]** Two invariants held through the surge — they eliminate the two obvious suspects:

```
db_fds (handles on data/secretary.db) : 60 / 60 / 60  at 23:17:28, 23:18:45, 23:19:06   <- UNCHANGED
nlwp   (thread count)                 : 76 / 76 / 76  at the same three instants         <- UNCHANGED
```
So it is **not** a connection-count leak and **not** thread-stack leakage.

**Caveat:** the kernel merges adjacent anonymous VMAs with identical flags, so "one 7,393 MB mapping"
may be many contiguous allocations coalesced into one VMA rather than a single 7.4 GB `malloc`. What
is unambiguous: the allocations are large, private, anonymous, and inside the process.

---

## 4. The code paths, and what each one was tested against

### 4.1 ChromaDB / Rust vector layer — **RETRACTED as leading suspect** (was my error)

**[OBSERVED]** The facts I based the claim on, all still true:
- `Sep 15 23:34:42 kernel: tokio-rt-worker invoked oom-killer`.
- The thread inventory contains Rust runtimes:

```
$ for t in /proc/<pid>/task/*; do cat $t/comm; done | sort | uniq -c | sort -rn
     40 AnyIO worker th
      8 tokio-rt-worker        <- chromadb_rust_bindings runtime
      8 python
      2 sqlx-sqlite-wor
      2 ThreadPoolExecu
      1 autopilot
      1 apscheduler-boo
```
- `chromadb_rust_bindings.abi3.so` loaded and resident; 4 open descriptors on
  `data/chromadb/chroma.sqlite`, 2 on `data/mem0/chroma.sqlite`.
- ChromaDB is reached from `semantic_memory.py`, `workspace_search.py`, `repo_map.py`.

**[CORRECTION] The inference I drew from them was invalid, and this is the most important correction
in the report.** `X invoked oom-killer` means thread X made the allocation that *failed* — i.e. it is
the thread that happened to request a page when the system was already exhausted. It carries **no
information about which thread allocated the preceding 18 GB**. `tokio-rt-worker` was the trigger, not
the allocator. I treated a trigger as a cause, which is exactly the error class this system has been
burned by before.

**[OBSERVED] The decisive counter-evidence arrived after the claim:** `ce20ab28` — a change with
nothing to do with ChromaDB — is what actually stopped the runaway (§0). And the `11/SEGV` is better
explained as a native failure in an OOM-exhausted process than as a Rust allocator bug.

**Verdict: do not chase ChromaDB on this evidence.** It remains worth *watching* (a Rust extension
that can segfault is a real liability), but it is not implicated in the memory burst.
**Would still settle it if ever needed:** run the burst window with the vector paths disabled; if the
burst did not change, ChromaDB is clean.

<!-- original claim, kept for the record:
**[INFERRED]** A Rust extension that (a) owns the thread that triggers the OOM, (b) is bounded by no
SQLite pragma, and (c) is present at a segfault, is the best-supported remaining explanation for a
burst that fix #1 could not touch.
**Would confirm:** disable/bound the vector paths (semantic memory off, or cap embedding batch and
collection size) and re-run the burst window; or `memray`/`heaptrack` one embedding-heavy tick.
**Would falsify:** the same burst shape and rate with ChromaDB fully disabled — then the allocator is
Python-side, or in another native extension.
-->

### 4.2 SQLite per-connection cost — real contributor, and the driver **via the thread count**

**[OBSERVED]** As it was during kills 1–7:

```python
424:    conn.execute("PRAGMA cache_size=-64000")  # 64MB page cache (default is 2MB)
425:    conn.execute("PRAGMA temp_store=MEMORY")  # temp tables in RAM
```
with **one connection per thread** keyed on thread identity (`database.py:345` →
`f"{db_url}:{threading.get_ident()}"`). Ceiling = `live_threads × 64 MB`, unbounded — plus
`temp_store=MEMORY` letting any `ORDER BY` / `GROUP BY` / `DISTINCT` materialise in RAM.

**[OBSERVED]** The store is large and **`ANALYZE` has never run**, so the planner has no statistics:

```
$ sqlite3 "file:data/secretary.db?mode=ro" "PRAGMA page_size; PRAGMA page_count; PRAGMA freelist_count;"
4096 / 1355923 / 548              # 5.17 GB real data; only 2 MB free — not bloat
$ sqlite3 … "SELECT * FROM sqlite_stat1;"
Error: in prepare, no such table: sqlite_stat1
$ sqlite3 … "SELECT name, SUM(pgsize)/1048576 AS mb FROM dbstat GROUP BY name ORDER BY mb DESC LIMIT 5;"
dsh_session_events|1198   dsh_session_events_fts_content|1185   procedural_experiences|566
dsh_session_events_fts_data|479   dialpad_stats_record|350
$ sqlite3 … "SELECT COUNT(*), SUM(LENGTH(raw)), MAX(LENGTH(raw)) FROM dsh_session_events;"
278593|1140682626|821026          # 1.06 GB of raw text; largest single row 802 KB
```

**[OBSERVED]** Handles on `secretary.db` reached **60–66**; process-wide descriptors went
**50 → 129 → 196** in four minutes. **60 × 64 MB = a 3.8 GB floor that existed whether used or not.**
**[OBSERVED] Falsification:** commit `44e3f8e8` set 8 MB / `FILE`; kill #8 followed 12 minutes later.

### 4.3 Raw `sqlite3.connect()` outside `_get_conn` — **audited and falsified**

**[OBSERVED]** 40+ direct call sites that bypass the pragmas, across ~15 files:

```
app/main.py (10)                app/services/outbound_buffer.py (5)   ai_spend_tracker.py (4)
dialpad_sms_backfill.py (3)     creativity_scanner.py (3)            persistence_utils.py (3)
semantic_memory.py (2)          quickbooks_service.py (2)            plaid_ledger_ingest.py (2)
ai_gateway.py (2)               family_chat/hub.py (2)               identity_store.py, drn_phone_source.py,
mashgiach.py, google_voice.py, evolution_verifier.py, finance_source_registry.py, …
```

**[OBSERVED] Library defaults on such a connection, measured:**

```
raw conn on a FILE db   -> temp_store = 0   cache_size = -2000
raw conn on a MEMORY db -> temp_store = 0
compiled SQLITE_TEMP_STORE: 0
```

**[OBSERVED] Empirical test** (scratch DB in `/tmp`, 200,000 × 400 B, forced `ORDER BY`) — because
`temp_store=0` *defers* to a compile-time default and I refused to guess:

```
RSS before/after sort: 17 MB -> 21 MB (delta 4 MB)
temp files created: NONE
VERDICT: sort spilled to a FILE (bounded)
```

**Conclusion: a raw connection does not put a big sort in RAM, and its page cache is 2 MB.** These 40+
sites are not the 18 GB. One worth noting anyway: `main.py:1510` opens and closes a connection to
`accounting.db` on **every `/health` call** (the finance check) — no leak, but a per-request connect on
a polled path.

### 4.4 `/health` probe storm — real, and it **outlived** its own fix

**[OBSERVED]** `py-spy dump` at 23:11:57 caught **35 of 36 threads parked in the health probe**:

```
Thread 367112 (idle): "AnyIO worker thread"
    _get_conn (app/database.py:434)                 <- `with _db_lock:` on the store path
    _db_check (app/main.py:1443)
    run (anyio/_backends/_asyncio.py:1002)
```
`main.py:1447` was `await asyncio.wait_for(run_in_threadpool(_db_check), timeout=2.0)` — and
**`asyncio.wait_for` cannot cancel a thread already inside `run_in_threadpool`**, so a slow database
added parked threads rather than shedding them. `/health` is polled every few seconds by
`127.0.0.1`, `::1`, `71.104.140.242`, `192.168.50.23` and `2607:fb90:2e07:116:…`.

**[OBSERVED]** Handles on `secretary.db` went **16 → 66** in four minutes; post-`44e3f8e8` the
orchestrator measured **13 → 85 in five minutes**. **Fixed** by commit `ce20ab28` (single-flight +
10 s cache, service restarted 23:38).

**[OBSERVED] But the thread/connection manufacturing did not stop.** With `ce20ab28` live, sampled
during the first minutes of the new process:

```
23:40:10  RSS 828,704 kB   33 threads    61 fds    5 handles on secretary.db
23:40:30  RSS 1,001,632 kB 66 threads   138 fds   42 handles on secretary.db
```
**5 → 42 DB handles and 33 → 66 threads in 20 seconds, with the health memo already in place.** So
`/health` was *a* source, not *the* source. With 8 MB caches the consequence is ~0.5 GB rather than
3.8 GB, which is why this is no longer an emergency — but the manufacturing site is still unnamed and
should be found, because it is the same mechanism at a smaller multiplier. Candidate that fits an
unbounded thread-per-unit-of-work pattern: §4.5.

### 4.5 Unbounded abandoned `wf-tick` workers — real, still unfixed

**[OBSERVED]** `app/workforce.py:1417` builds a fresh `ThreadPoolExecutor` on every `company_tick`,
one worker per department plus the orchestrator, and leaks workers on timeout:

```python
1463:  log.warning("Worker tick for %s exceeded %ss — abandoned (continues in background)", …)
1477:  finally:
1478:      _worker_executor.shutdown(wait=False)     # does NOT cancel running futures
```
`wf-tick_0` is what the kernel blamed for OOM #1 (`Sep 15 13:34:32 kernel: wf-tick_0 invoked
oom-killer`). Through the 23:18–23:19 surge `nlwp` was constant at 76 and no `wf-tick` threads were
present, so **I cannot attribute the cliff to it** — but it is the best fit for a *persistent*
thread/connection manufacturing rate, and it creates per-thread DB connections. **This is my top
candidate for the residual 20-second 5 → 42 growth in §4.4 and worth instrumenting next.**

### 4.6 DSH ingest — minor contributor

**[OBSERVED]** Called in storms and retried on failure, not every 30 minutes:

```
22:08:15 .. 22:09:02  14 calls in 47 s
22:11:24 .. 22:12:20   9 calls in 60 s
22:05:55 .. 22:06:14   4 calls in 19 s   ← 17 s before the 22:06:31 OOM
22:09:33 ERROR … ingest: database is locked
23:13:28 ERROR … ingest: Cannot operate on a closed database.
```
A thread was caught in `ingest_export (dsh_session_ingest.py:335)`, the FTS5 reindex.
**[INFERRED]** `Cannot operate on a closed database` is a live correctness bug — the connection cache
closed a connection a live caller still held, exactly the hazard the new in-repo comment records.

### 4.7 Ruled out with evidence

| Suspect | Evidence |
|---|---|
| Connection-count leak *as the burst* | `db_fds` constant at 60 through a +9 GB surge |
| Thread-stack leak | `nlwp` constant at 76 through the same surge |
| SQLite page cache / `temp_store` *as the burst* | tested in production by `44e3f8e8`; kill #8 followed |
| Raw `sqlite3.connect()` sites | defaults measured (2 MB cache, `temp_store=0`); 200k-row sort moved RSS 4 MB; sorts spill to file |
| DSH full-text **search** | `dsh_session_ingest.py:415` clamps `limit` ≤200 and selects `snippet(...)`, not `raw` |
| DSH ingest reading huge blobs | `raw` rows 83 B – 802 KB; all 547 sessions declare 0.30 GB total; heaviest session 42 MB |
| FTS/table bloat | `PRAGMA freelist_count` = 548 pages (2 MB) ⇒ 5.17 GB is real data |
| Ingest full scans | `idx_dsh_session_events_seq (source_machine, session_id, seq)` covers its `WHERE` |
| `google_voice._scan` | `google_voice.py:2046` skips any file `> 20 * 1024 * 1024` |
| `GET /api/v1/gbp/rating` | `main.py:6119-6121` 500s **before** any network call (missing key) |
| `_ASYNC_CLIENTS` / `_ACCOUNTING_WORKERS` | `_ACCOUNTING_WORKERS[:] = [worker]` bounds to 1; `_ASYNC_CLIENTS.clear()` exists |
| WAL growth | `journal_size_limit=67108864`; WAL file exactly 64 MB |
| Noisy neighbours | kernel task table: API = 19.3 GB of 22 GB total anon; next-largest 529 MB |
| Thread churn generally | real but **flat during the surge**, and ~6–8 MB of *virtual* each |

---

## 5. Ranking (final, after the production tests)

| # | Cause | Status | Decisive evidence |
|---|---|---|---|
| **1** | **Thread/connection manufacturing × a per-thread SQLite connection carrying a large page cache** — the product `threads × cache_size`, with `threads` unbounded | **STOPPED by `44e3f8e8` + `ce20ab28`** | py-spy caught 35/36 threads in the probe on the cache lock; handles 16→66 and 13→85 in minutes; **with both fixes live the process is flat at ~1.8 GB for 10+ min, handles constant at 42, 0 kills** |
| 2 | The 64 MB `cache_size` acting as the **multiplier** in #1 | **confirmed as a multiplier, not as a standalone cause** | 9 mappings exactly 64 MB; `44e3f8e8` alone (8 MB) still OOM'd at 23:34:43 — so it lowered the ceiling without removing the storm |
| 3 | `/health` probe storm as the **source** of the thread growth | **fixed** (`ce20ab28`, 23:38) | py-spy evidence above; `asyncio.wait_for` could not cancel the threadpool worker. Residual: **5 → 42 handles in 20 s even after the fix**, so a second source exists |
| 4 | Unbounded abandoned `wf-tick` workers | **best fit for #3's residual; still unmeasured** | per-tick `ThreadPoolExecutor` + `shutdown(wait=False)`; `wf-tick_0` blamed for OOM #1 |
| 5 | DSH ingest retry storms / lock churn | minor | 14 calls/47 s; `database is locked`; `Cannot operate on a closed database` |
| 6 | No memory containment | amplifier, still unaddressed | `MemoryMax=infinity`; every kill `global_oom`; swap exhausted |
| — | **ChromaDB / Rust vector layer** | **retracted — not implicated** | `tokio-rt-worker invoked oom-killer` names the thread that *triggered* the kill, not the allocator (§4.1) |
| — | Raw `sqlite3.connect()` outside `_get_conn` | **falsified** | defaults measured (2 MB cache, `temp_store=0`); 200k-row sort moved RSS 4 MB and spilled to file (§4.3) |

---

## 6. The fix

### 6.1 Already landed and live — tested, and insufficient on their own
- `44e3f8e8` — `cache_size` 8 MB, `temp_store=FILE` (baseline lowered; **does not stop the burst**).
- `ce20ab28` — single-flight + 10 s cached `/health` probe (`PS_HEALTH_DB_CACHE_S`), restarted 23:38.
  This closes the mechanism py-spy caught at 23:11:57. Keep both.

### 6.2 My patch — delta on HEAD, now **2 hunks / 1 file**
`/home/zabz/phone/api-oom-fix.patch` — `git apply --check` **clean** against current HEAD, and I
applied it to a throwaway copy and `ast.parse`d the result (clean, `hard_heap_limit` present).

It is now **only** the hard per-connection SQLite heap ceiling: `SQLITE_HARD_HEAP_MB` (default 1024;
`PS_SQLITE_HARD_HEAP_LIMIT_MB=0` disables) applied as `PRAGMA hard_heap_limit`, **verified honoured by
the installed SQLite 3.46.1**. My earlier `/health` hunk is **withdrawn** — `ce20ab28` implemented it
better (with real single-flight).

**Why keep it anyway, now that the theory changed twice:** the burst has survived two of my own
explanations, and the current stability rests on **13 minutes** of evidence against a failure that has
previously taken as long as **62 minutes** to appear. So a cheap guard against the *next* surprise is
worth keeping — it converts "one of five subsystems ate the box" into an **attributable
`SQLITE_NOMEM`**. It is safe, reversible by one env var, and independently justified.
*Honest framing:* this is **defensive, not the fix.** The fix is `44e3f8e8` + `ce20ab28`.
*Tradeoff:* a legitimate statement needing >1 GiB now fails instead of succeeding slowly; 1 GiB is
~1.5× the app's entire healthy RSS. Drop this hunk if you prefer zero new failure modes — nothing
else in this report depends on it.

### 6.3 Containment — still worth doing, and now cheaper to justify
`/home/zabz/phone/api-oom-systemd-memory-guard.conf` — `MemoryHigh=3G`, `MemoryMax=6G`,
`MemorySwapMax=1G`. Not a fix; it converts a host-wide kill into a recorded per-service restart, and
bounds the blast radius **while the soak test runs**. Note the new steady state is ~1.8 GB, so a 3 GB
`MemoryHigh` leaves real headroom without hiding a return of the storm.

### 6.4 Acceptance test — **a soak, not a snapshot**
| Metric | How | Baseline | Pass |
|---|---|---|---|
| RSS **flat** for ≥60 min | `oom-evidence/burst-catcher.log` (`rss_mb` column) | 19–20 GB at death; 62 min was the longest pre-fix survival | **flat, < 2 GB, for ≥60 min** |
| Largest anon mapping | `python3 oom-evidence/counter_fixed.py 1` (`rss_top1_MB`) | 7,393 MB | **< 200 MB** |
| Maps ≥56 MB | same (`maps_ge56MB` / `rss_ge56MB_MB`) | 19 / 11,574 MB | **0** |
| DB handles | same (`db_fds`) | 60→66; 5→42 in 20 s | **constant** (currently 42) |
| OOM kills / segfaults | `journalctl -u secretary-api \| grep -cE 'oom-kill\|status=11/SEGV'` | 8 / 1 | **0 over the soak** |

**The 13-minute plateau in §0 is a strong early signal, not the acceptance test.** The pre-fix
failure times were 15, 54 and 62 minutes as well as 6.5 — so **run for at least an hour before
believing it.** If it does recur, `burst-catcher.sh` + `analyze_burst.py` (§7) will name the frames
automatically rather than requiring another investigation.

---

## 7. What I could not determine — plainly, and what will

**If the runaway is in fact stopped, then the cause is identified: `threads × cache_size`, with
`threads` driven by the `/health` probe storm.** What is *not* yet identified is the **residual**
manufacturing — `db_fds` still went 5 → 42 in 20 s after `ce20ab28` (§4.4) — and the exact allocation
that produced the 7,393 MB single mapping. If the burst returns, this is why:

- **`py-spy` is a *sampling* profiler and the burst is a ~35 s event.** The whole 23:18:00–23:19:17
  window contains only a Twilio poll and one `gbp/rating` 500 — no agent-worker lines, no ingest, no
  query logs. A CPU sampler has no frame to attribute across an 18 GB / 35 s allocation.
- **Allocation *tracing* answers this in one run, and I did not use it**, because `tracemalloc`,
  `memray` and `heaptrack` all require instrumenting the running process — outside my read-only
  mandate. That is a limit of my instructions, not of the tools; it is the parent's call.
- The kernel merges adjacent anonymous VMAs, so `/proc` alone cannot say whether the 7,393 MB region
  is one allocation or many contiguous ones.

**Instrumentation that is already armed (not mine to fire):**
- `/home/zabz/phone/oom-evidence/burst-catcher.sh` (armed by the orchestrator) polls RSS every 2 s and
  on the 5 GB crossing takes three `py-spy` dumps + `smaps-top-25` into `oom-evidence/burst-*.txt`.
- `/home/zabz/phone/oom-evidence/analyze_burst.py` (mine) waits for those files and writes
  `burst-analysis.txt`, ranking each thread by whether its top app-level frame is an allocating call
  (`fetchall`/`read_bytes`/`json.loads`/`execute`/`embed`/`add`/`upsert`/`encode`). **Run it with the
  catcher and the frames get named automatically.** Nothing had fired as of 23:41.
- `/home/zabz/phone/oom-evidence/counter_fixed.py` keeps the continuous RSS/handle/mapping series.

---

## 8. Artifacts and method

| Path | Contents |
|---|---|
| `/home/zabz/phone/api-oom-report-2026-09-15.md` | this report |
| `/home/zabz/phone/api-oom-fix.patch` | delta fix — 2 hunks, 1 file (`hard_heap_limit`); `git apply --check` clean |
| `/home/zabz/phone/api-oom-systemd-memory-guard.conf` | containment drop-in + install notes |
| `oom-evidence/oom-full-2300.txt` | full kernel OOM report incl. per-task RSS table |
| `oom-evidence/counter.tsv` | pre-fix RSS / `db_fds` / big-mapping series (§2, §3) |
| `oom-evidence/counter-fixed.tsv` | continuous series, correct PID matching (§4.4) |
| `oom-evidence/journal-*`, `rss-samples.tsv` | growth curves |
| `oom-evidence/pyspy-dump-full.txt` | py-spy dump: 35/36 threads in the health probe |
| `oom-evidence/db-size-probe.txt` | per-table sizes, `raw` totals, heaviest sessions |
| `oom-evidence/counter*.py`, `analyze_burst.py` | measurement + burst analysis tools |
| `oom-evidence/pyspy/` | py-spy 0.4.2 unpacked here — **not** installed into the app venv |

**Provenance caveats recorded rather than silently fixed:**
- `pgrep -f 'uvicorn app.main:app'` also matches **shell wrappers** whose command line contains that
  string. Between 23:28:43 and 23:37:44 my `counter-postfix.tsv` therefore recorded a 1-thread, 3-fd
  bash process instead of the API. Only the **23:26:23 / 23:26:43** rows are valid post-fix API
  samples. The pattern is now anchored to the binary path (`counter_fixed.py`); the raw file is left
  as captured and this note is the correction.
- **Two parser bugs that produced confident zeros before I caught them:** (1) in
  `/proc/<pid>/smaps` the `Size:`/`Rss:` fields are **not indented**, so any "starts with whitespace ⇒
  sub-field" test silently yields **zero** mappings — my first two parsers reported 0 while the
  process held 18 such mappings; (2) an `AnnAssign` (`X: dict = {}`) is not an `ast.Assign`, so a
  naive scope checker misses module-level constants.
- **A bug I found in my own withdrawn patch:** `asyncio` is imported *inside* functions throughout
  `main.py`, never at module scope, so extracting the health probe into a module-level helper would
  have raised `NameError` on the first `/health` call. Caught before shipping; moot now that
  `ce20ab28` landed.

**Method:** `py-spy` was absent from the host. Its wheel was downloaded and **unpacked** (never
installed) to `oom-evidence/pyspy/`, then run as a standalone binary under `sudo -n`; it attaches and
reads only. No packages were installed into the app venv, and no app file, database or service was
touched.
