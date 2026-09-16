# Incident: `secretary-api` memory runaway → OOM kills (2026-09-15/16) — evidence archive

**Status: OPEN.** Contained, not fixed. The API still grows to a multi-GB footprint and is killed; the allocation that does it
has not been named yet. This folder is the durable copy of the evidence behind journal **P211**, **H389**, **H390** and
**L1735** — it lives in git because `~/phone/` is a scratch desk that is not backed up.

## What is happening, in numbers

| Date | OOM kills of this process | Other |
|---|---|---|
| 2026-09-15 | **8** (13:34, 20:12, 20:41, 21:01, 22:06, 23:00, 23:19, 23:34) | `status=11/SEGV` at 23:37:43 |
| 2026-09-16 | **23** (hourly 00:00 → 13:18; 1–3 per hour) | `code=dumped, status=7/BUS` (SIGBUS) at 14:35:22, 14.3 GB peak |

Every kill is the same process signature: `(python)`, `anon-rss` **20.2–20.8 GB**, `total-vm` ~23.5–25 GB, and
`constraint=CONSTRAINT_NONE … global_oom` — the *host's* OOM killer choosing a victim, not a cgroup limit.

Survival times observed: 6.5, 15, 26, 34, 42, 54, 62 minutes. The tail of the 09-15 observation showed a **burst**: RSS
743 MB → 1,071 → 1,600 MB → dead at 19.9 GB, with one anonymous mapping growing 958 MB → 7,393 MB — i.e. ~18 GB inside a
~35-second band.

## What was tried, and what it actually did

| Change | Commit | Measured effect |
|---|---|---|
| Watchdog startup grace (`STARTUP_GRACE_SECONDS=600`) — a cold start is minutes, so the 60 s watchdog was restarting the API before it ever finished booting | `71547526` | Stopped the restart *flap* (kill → daemon restart → watchdog restart → stop-sigterm SIGKILL → repeat). Did not touch the leak. |
| `PRAGMA cache_size` 64 MB → 8 MB per connection; `PRAGMA temp_store` MEMORY → FILE (env: `PS_SQLITE_CACHE_KB`, `PS_SQLITE_TEMP_STORE`) | `44e3f8e8` | Page cache per connection × live threads was a 3.8 GB floor at 60 connections; DB handles at the same age fell 60 → 13. **The OOM continued**, which falsified the in-memory-temp-store theory. |
| `/health` DB probe: single-flight + 10 s cache (env: `PS_HEALTH_DB_CACHE_S`) — a `py-spy` dump caught **35 of 36 threads parked in `_get_conn <- _db_check`** on the connection-cache lock, so probe rate was setting thread *and* connection count | `ce20ab28` | Removed that source. The failure interval moved from 6.5 minutes to 30–60 minutes — real progress, **not** a fix: kills resumed inside the same night. |
| **Containment (applied 2026-09-16):** `MemoryHigh=5G`, `MemoryMax=8G`, `MemorySwapMax=1G` on the unit | drop-in `20-memory-guard.conf` | Not yet measured over a full failure cycle. The kill now happens inside the unit's cgroup at 8 GB instead of harvesting box memory at 20 GB. |

Note the proposal file in this folder (`proposed-systemd-memory-guard.conf`, written before the second kill wave) argues for
3G/6G. What was actually installed is 5G/8G (the archive captures the intent, the installed values are the ones recorded in
the journal entry H390).

## Leading hypotheses, ranked (from `diagnosis-report.md`)

1. **Thread-per-request storm × per-thread SQLite connection × per-connection page cache.** Unbounded because `threads`
   climbed with request rate. `44e3f8e8` cut the multiplier 8×, `ce20ab28` removed the probe-driven part. `db_fds` still went
   5 → 42 in 20 s *after* the health fix, so at least one more source of threads/connections remains.
2. **`app/workforce.py:1417`** — a fresh `ThreadPoolExecutor` on every company tick, and `shutdown(wait=False)` does not
   cancel running futures, so abandoned ticks ("continues in background") accumulate with their own threads, connections and
   LLM conversation history. A `wf-tick_0` thread was blamed by the kernel for the first OOM of 09-15. **Not yet
   instrumented.**
3. An un-named multi-GB allocation that is neither SQLite's temp store (falsified by measurement) nor a raw
   `sqlite3.connect()` outside `_get_conn` (falsified: library defaults are 2 MB cache; a 200,000-row × 400 B `ORDER BY` on
   a raw connection moved RSS by 4 MB and spilled to disk).

Two premises were **wrong** and corrected in the record rather than quietly dropped: the kill count on 09-15 is 8 (not 6),
and `tokio-rt-worker invoked oom-killer` names whichever thread requested the next page after memory is already exhausted —
the trigger, not the allocator (the subagent retracted its own ChromaDB/Rust suspect on exactly this ground).

## How to catch the allocator (next session)

```bash
# py-spy is already extracted; nothing to install
PYSPY=~/phone/oom-evidence/pyspy/py_spy-0.4.2.data/scripts/py-spy
$PYSPY dump --pid $(pgrep -f 'personal-secretary-mvp/.venv/bin/python.*uvicorn')

# armed watcher: polls RSS every 2 s; on crossing 5 GB takes three py-spy dumps
# plus a smaps top-25. Give it HOURS, not minutes: the failure interval is 30-60 min.
~/phone/oom-evidence/burst-catcher.sh 21600     # 6 h, logs to burst-catcher.log
```

Nothing fired the 5 GB trigger during the 09-15 window, so there are no frames in this archive. A 40-minute watch against a
30–60 minute failure interval is a coin flip (L1735).

## Files

| File | What it is |
|---|---|
| `diagnosis-report.md` | The full read-only diagnosis (subagent `891b5fbc`), every claim tagged OBSERVED or INFERRED, with corrections. 30 KB. |
| `proposed-hard-heap-limit.patch` | Reviewed, `git apply --check` clean, **not applied**: `PRAGMA hard_heap_limit` so a runaway statement raises `SQLITE_NOMEM` instead of a host-wide kill. |
| `proposed-systemd-memory-guard.conf` | The containment drop-in (installed variant uses 5G/8G). |
| `soak-2026-09-15.tsv` | My 60 s sampler: 176 rows, peak 4,571 MB, one `GONE` — the process it watched died and was replaced. This is the file that disproves "the fix holds". |
| `counter-prefix.tsv` / `counter-postfix.tsv` | The subagent's 20 s counters either side of the first fix: DB handle and thread counts. |
| `rss-after-fix2.tsv` | 30 s series with threads, DB fds and largest anonymous mapping. |
| `kernel-task-table-at-2300-kill.txt` | The kernel's per-task table at the 23:00 kill: the API was **84 % of all anonymous memory on the box**. |
| `pyspy-dump-2311-health-probe-park.txt` | The 23:11:57 py-spy dump: 35 of 36 threads parked in `_get_conn <- _db_check`. |
| `smaps-rollup-prefix.tsv` | Anonymous mapping growth before the first fix. |

## Where the fixes live, and what is saved where (as of 2026-09-16 16:20Z)

| Thing | Location |
|---|---|
| Watchdog startup grace | authority `personal-secretary-mvp`, commit `71547526` (branch `master`) |
| SQLite per-connection memory + `temp_store=FILE` | commit `44e3f8e8` |
| Single-flight cached `/health` DB probe | commit `ce20ab28` |
| All three, off-machine | pushed today as **`origin/backup/secratary-checkout-20260916`** on GitHub (the authority checkout is 103 commits ahead of `origin/master` and must never be pushed there blindly — P143) |
| Containment | `/etc/systemd/system/secretary-api.service.d/20-memory-guard.conf` on the authority (`MemoryHigh=5G MemoryMax=8G MemorySwapMax=1G`), applied at runtime with `set-property --runtime` so the running unit is covered; reversible without a restart |
| Evidence capture | `~/phone/oom-evidence/burst-catcher.sh <seconds>` armed 2026-09-16 16:0xZ for 6 h → `burst-catcher.log`, `burst-*.dump.txt` |
| Journal record | `P211` (pain, open), `D211` (containment decision), `L1734` (SQLite memory), `L1735` (how to judge a provisional fix), `H390` (the corrected state of play), `P212` (the id-collision defect found while saving this) |
