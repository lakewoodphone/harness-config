# 182 — Database lock contention: root cause, and the Postgres question

**Investigated by:** mesh child session whose shell ran on **`zabz-tech-linux`**, driving the
target **`secratary-cloud`** over ssh (`root@178.156.194.1`, key `~/.ssh/id_ed25519_hetzner`),
2026-10-12 ~13:54–14:00Z.
**Target:** `secratary-cloud` (kernel `7.0.0-38-generic`, Ubuntu 26.04), 4 vCPU / 15 GiB,
`company-api` PID 1084, DB `/root/authority.db` (24 503 566 336 B), Python 3.14.4.
**Posture:** read-only on the live system. No service was started, stopped, restarted, enabled,
disabled or masked. Nothing was written under `/root` or `/opt` except this report and its git
commit. Scratch tools were installed only under `/tmp` (py-spy) and `/tmp` scripts. The database
was opened `mode=ro` for one schema census only; **no** `BEGIN IMMEDIATE`/`PRAGMA`-write/VACUUM
probe was run (see §6).
**Standard:** every number carries the command that produced it. Commands are in §8.

---

## 0. The root cause, in one sentence

**The application funnels *all* database access through one process-wide
`threading.RLock` (`app/database.py:27 _db_lock = threading.RLock()`), and holds it across
multi-second, multi-query work — caught live at `capture_freshness()` — and because the blocking
DB code is executed *inline on the asyncio event loop* by `async def` handlers, every other
thread and request queues behind it; SQLite itself is a bystander.**

Supporting one-liners:

1. **The lock is the application's, not SQLite's.** `journalctl` over the live window
   (`2026-10-11T00:00:22Z` → `2026-10-12T13:59Z`) shows **616** `_db_lock contended` waits and
   **199** `/health` "db check timed out", against only **12** `database is locked` events from the
   SQLite engine.
2. **The exact prior figure reproduces:** the busiest rolling 30-minute window is **71**
   `_db_lock contended` waits, `2026-10-12 04:00:10Z → 04:30:10Z`.
3. **Both the request wall-clock queue and the health timeout are the same bug.** A `py-spy` dump
   taken while `/health` was degraded shows the event-loop thread `active+gil` inside
   `capture_freshness()` holding `_db_lock`.
4. **PostgreSQL does not fix this.** Postgres would remove SQLite's single-writer serialisation
   (12 events in ~38 h here); it cannot remove an `RLock` in `app/database.py`, and it would leave
   the event-loop blocking untouched. See §5.

---

## 1. Find the lock

### 1.1 Definition and type

```
$ grep -n '_db_lock\s*=' /opt/company/app/database.py
27:_db_lock = threading.RLock()
```

```
/opt/company/app/database.py:27: _db_lock = threading.RLock()
```

It is a **process-wide, reentrant `threading.RLock`** — not an asyncio lock, not a semaphore, not a
connection pool of size one. `_connections` (an `OrderedDict` keyed by `url:thread_id`) is the
per-thread connection cache; `_db_lock` guards both that dict *and* — at the hundreds of call
sites — whole read/write transactions.

### 1.2 Every place it is acquired

```
$ grep -rIo 'with _db_lock' /opt/company/app --include='*.py' | wc -l
544
$ grep -c 'with _db_lock' /opt/company/app/database.py
198
$ grep -rIo '_db_lock.acquire' /opt/company/app --include='*.py' | wc -l
2
```

* **544** `with _db_lock:` blocks across `/opt/company/app`, **198** of them inside `database.py`
  alone. (The raw textual count `_db_lock` is 823; the 544 are the `with` statements.)
* The only two explicit `acquire` calls are both in `_get_conn`:

```
/opt/company/app/database.py:1082  def _get_conn(db_url):
...
1104    acquired = _db_lock.acquire(timeout=2.0)
1105    if not acquired:
1109        _log.warning("_get_conn: _db_lock contended for key %s, waiting...", key)
1110        _db_lock.acquire()  # block until acquired
...
1166        _db_lock.release()
```

So the **exact warning the previous session counted fires when a thread cannot take `_db_lock`
within 2 s** and then blocks forever. The `/health` probe wraps this same call in a 2 s
`asyncio.wait_for` (`app/main.py:1454-1520`), so a hold longer than ~2 s *is* a health timeout.

### 1.3 Is it held across network / LLM / file IO?

Almost never. An AST scan of every `with _db_lock:` block in `/opt/company/app` (script in §8)
finds exactly **one** network/IO call lexically inside such a block:

```
TOTAL network/IO calls lexically inside a `with _db_lock:` block: 1
    1  io:fp.write_bytes   e.g. services/dialpad_webcrawler.py:4702 fp.write_bytes
```

**The lock is held across database work, not across HTTP/LLM/file IO.** That is what makes it
attractive to remove/replace; it is *not* a lock that must be held over an external call.

---

## 2. Name the holder

`py-spy` is not installed on the box; I installed **py-spy 0.4.2 under `/tmp` only**
(`/opt/company/.venv/bin/pip install --prefix=/tmp/pyspy py-spy`) and used
`/tmp/pyspy/bin/py-spy dump --pid 1084`. It works on CPython 3.14.4.

### 2.1 Direct capture (the smoking gun)

While `/api/v1/comms/freshness` was being served, a dump caught the **event-loop thread** holding
the lock:

```
Process 1084: /opt/company/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 ...
Python v3.14.4 (/usr/bin/python3.14)

Thread 1084 (active+gil)
    _department_snippet_has_body_evidence (unified_comms.py:218)
    _dialpad_sms_body_coverage (unified_comms.py:431)
    capture_freshness (unified_comms.py:2088)
    comms_freshness (app/main.py:6717)
    run_endpoint_function (fastapi/routing.py:213)
    ...
```

`capture_freshness()` (`app/services/unified_comms.py:2014`) takes **one `with _db_lock:` around
~12 queries** — nine `SELECT MAX(...)` freshness scans across `dialpad_sms_cache`,
`dialpad_call_full`, `dialpad_digital_session`, `dialpad_transcript_cache`, the four
`dialpad_ui_*` tables and `sms_log`, then body-coverage and reconciliation rollups:

```
unified_comms.py:2064    with _db_lock:
unified_comms.py:2065        conn = _conn()
...                          for label, sql in queries: conn.execute(sql).fetchone()[0]
                             _dialpad_sms_body_coverage(conn)      # scanner, line 431
                             _dialpad_voice_coverage(conn)
                             _count_recent_active_phones(conn, hours=24)
                             _reconciliation_rollup(conn)
```

Measured cost of one call: **2.53 s and 3.14 s** (`curl -w '%{time_total}'`). The health probe
gives up at 2.0 s, so a single `capture_freshness()` is sufficient to produce the observed
`"db check timed out (lock contention)"`.

### 2.2 Who calls it, and why it recurs

```
$ grep -rn 'capture_freshness' /opt/company/app --include='*.py'
main.py:6714-6717           # GET /api/v1/comms/freshness  (async def, called inline)
autopilot.py:9033-9037      # _maybe_check_comms_freshness() -- hourly (now_ts - last_check < 3600)
owner_checkin.py:377-383
daily_reconciliation.py:915-917
```

`comms_freshness()` (`app/main.py:6712`) is **`async def`** and calls the blocking
`capture_freshness()` **directly, not via `run_in_threadpool`** — so while it holds `_db_lock` it
also **blocks the entire event loop**. That is why an unrelated `/health` request can stall for
almost a second (§3.2).

The same shape exists elsewhere. `GET /api/v1/comms/active-phones` is also `async def` and calls
`list_active_customer_phones()` inline; that function does `with _db_lock:` around two
`GROUP BY` scans:

```
/opt/company/app/services/unified_comms.py:2213  with _db_lock:
```

The second discovered holder is the hourly DSH batch ingest
`POST /api/v1/owner/dsh-sessions/ingest`: `dsh_session_ingest.py:93` and `:272` each take
`_db_lock` per session in a loop, on top of a `BEGIN IMMEDIATE` write transaction
(`dsh_session_ingest.py:222`). The 04:12–04:13 burst in the journal is exactly those POSTs
(04:12:06, 04:13:01, 04:13:20) plus `lifecycle_sweep` at 04:13:11, whose customer-stall step itself
logged `database is locked` at 04:13:11.

**Longest single hold:** `capture_freshness()` (§2.1). **Most frequent holders:** the
autopilot/owner-checkin/daily-reconciliation callers of `capture_freshness`, the DSH batch ingest,
and `lifecycle_sweep`.

### 2.3 What I could not establish

I could not catch a dump of a thread *statically parked* in `_get_conn` for the whole process
(multi-second windows are rare and millisecond-scale acquisition is the norm); the dumps instead
caught the **holder** (the highest-value half). `py-spy` profiler mode
(`record`/`top`) was not used — it samples but adds no lock-owner information beyond what the dump
already gave, and the process was not reproduced stall-for-stall. I did **not** attach a debugger
or inject code.

---

## 3. Quantify it (controlled, read-only load test)

Script `/tmp/loadtest_182.py` (full source in §8): barrier-synchronised worker threads, 6 rounds
per level, one request per worker per round, per-request wall time via `urllib`. Target endpoint:
**`GET /api/v1/comms/active-phones`** (read-only; `with _db_lock` around two `GROUP BY` scans).

### 3.1 Result — `/api/v1/comms/active-phones`

| concurrency | requests | errors | p50 (ms) | p95 (ms) | max (ms) | mean (ms) |
|---:|---:|---:|---:|---:|---:|---:|
| 1  | 6   | 0 | **61.6** | 69.0 | 69.0 | 63.0 |
| 4  | 24  | 0 | **244.0** | 249.0 | 249.2 | 229.1 |
| 8  | 48  | 0 | **491.7** | 629.9 | 630.5 | 471.1 |
| 16 | 96  | 0 | **826.5** | 985.8 | 1025.1 | 786.8 |
| 32 | 192 | 0 | **1318.6** | 2839.2 | 3346.1 | 1476.5 |

**This is a queue, not saturation:** p50 grows **×3.96 at c=4 and ×7.98 at c=8** — essentially
perfect linear scaling with concurrency (61 → 244 → 492 ms), then ×13.4 at c=16 and ×21.4 at
c=32 (sub-linear, because some HTTP plumbing overlaps). p95 at c=32 (2.84 s) is exactly the
regime where the `/health` 2 s budget is breached.

### 3.2 Control — `GET /health` (same script)

`/health` uses a single-flight `asyncio.Lock` + 10 s cache and offloads its DB probe via
`run_in_threadpool`, so it mostly bypasses the queue:

| concurrency | p50 (ms) | p95 (ms) | max (ms) |
|---:|---:|---:|---:|
| 1  | 7.5  | 15.8  | 15.8 |
| 4  | 18.8 | 162.4 | 162.4 |
| 8  | 27.9 | 35.7  | 36.5 |
| 16 | 48.2 | 65.0  | 67.0 |
| 32 | 72.0 | 125.5 | 131.9 |

No blow-up. **The web server, sockets and TLS are not the limit; the DB path is.**

### 3.3 Event-loop isolation

Baseline `/health` while idle: 5.9, 7.2, 7.8, 8.1, 9.1, 16.7 ms. With **16 concurrent
`active-phones`** in flight, the first `/health` took **906.8 ms** (≈**130×** baseline); the
following ones were 7–13 ms once the queue drained. That is the `async def` handler running
blocking `_db_lock`/SQLite work on the event loop: even a non-DB route cannot be scheduled.

---

## 4. Separate the layers

| layer | bottleneck? | evidence |
|---|---|---|
| **(a) app global lock** | **YES — the cause** | 616 `_db_lock contended` waits and 199 health timeouts in ~38 h; `/tmp/pyspy` dump of Thread 1084 `active+gil` inside `capture_freshness` holding `_db_lock`; 544 `with _db_lock:` sites; linear load-test queue. |
| **(b) SQLite single-writer** | **No — a bystander here** | Only **12** `database is locked` events in the same ~38 h (vs 616 app-lock waits). WAL + `PRAGMA busy_timeout=10000` are configured (`database.py:656 _configure_connection`: WAL, busy_timeout, synchronous=NORMAL, cache_size=-8000, temp_store=FILE, wal_autocheckpoint=10000, journal_size_limit=64 MB). The app already serialises writers itself with `_db_lock`, so SQLite rarely sees a conflict. Cross-process cron writers (e.g. `comms-refresh`) can contend, but they are not what fills the journal. |
| **(c) disk** | **No** | `iostat -x 1 2`: `sda` `%util` 19.17 → 0.20 %, `r_await` 0.09 ms, `w_await` 0.67 ms. `df -h /root`: 75 G, 56 G used, **16 G free (78 %)**. |
| **(d) CPU** | **No** | `uptime`: load **0.89 / 0.73 / 0.67** on **4** vCPU; `vmstat 1 5` shows **83–100 % idle**. A single scan is single-threaded, but the box has headroom. |
| **(e) the GIL** | **Contributory, not the serialiser** | One uvloop thread + one CPython interpreter, so Python bytecode is serial anyway; `py-spy` reports Thread 1084 `(active+gil)`. But SQLite releases the GIL inside its C calls, and the explicit queue is `_db_lock`. Fixing `_db_lock`/event-loop blocking is the actionable change; "the GIL" is not something Postgres changes for an in-process lock. |
| **(f) uvicorn worker count** | **1 worker** | `ExecStart=/opt/company/.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8002 --proxy-headers --forwarded-allow-ips=127.0.0.1` — **no `--workers`**, so uvicorn defaults to **1** process. `systemctl show company-api -p MainPID -p TasksCurrent` → `MainPID=1084`, `TasksCurrent=46`; `ps` shows one PID. One process ⇒ one `_db_lock`, one event loop, one GIL. (py-spy sees 13 Python-level threads; the other OS tasks are C/library threads.) Adding workers would give each process its own `_db_lock`, but then SQLite's single writer — and this app's in-process schedulers/caches, which assume one process — become the binding constraints. |

**Net:** the binding constraint is (a), amplified by executing it on the event loop. Not (b)–(f).

---

## 5. The Postgres question

Counts are from `/opt/company/app` (live checkout) and a `mode=ro` schema census of
`/root/authority.db`.

### 5.1 How much SQLite-specific surface exists

```
py files importing sqlite3 : 75
files referencing sqlite3  : 83
.execute( calls            : 2031
.executemany( calls        : 9
PRAGMA occurrences         : 80
  PRAGMA table_info        : 37
  PRAGMA busy_timeout      : 21
  PRAGMA journal_mode      : 7
  PRAGMA foreign_keys      : 5
  ... (synchronous, wal_checkpoint, wal_autocheckpoint, user_version, temp_store,
       journal_size_limit, cache_size)
fts5/FTS5 occurrences      : 38
CREATE VIRTUAL TABLE       : 9
MATCH (FTS query)          : 7
sqlite_master refs         : 31
AUTOINCREMENT              : 147
INSERT OR REPLACE          : 25
INSERT OR IGNORE           : 38
strftime( refs             : 248
datetime( SQL refs         : 201
sqlite3.Row refs           : 98
check_same_thread refs     : 5
run_in_threadpool refs      : 45
async def defs (main.py)   : 103
sync    def defs (main.py)  : 663
```

Schema census (`mode=ro`):

```
tables   = 231
views    = 9
indexes  = 409
triggers = 5
fts5_tables = 3  ['vscode_chat_sessions_fts', 'memories_fts', 'dsh_session_events_fts']
```

So: **231 tables, 2 031 hand-written `.execute(` statements across 75 modules, 80 `PRAGMA`s, and 3
FTS5 full-text virtual tables** (plus 9 `CREATE VIRTUAL TABLE` sites). The search surface is
real and used (`MATCH` at 7 sites; the FTS tables back VS Code chats, memories and DSH session
events).

### 5.2 Verdict

> **Moving to PostgreSQL would not remove the observed contention.** The 616 contended waits and
> 199 health timeouts are waits on `app.database._db_lock`, a Python `RLock`. Postgres does not
> know that object exists. It would remove *SQLite's single-writer serialisation*, which on this
> box produced only **12 `database is locked` events in ~38 h** — i.e. it would fix a symptom this
> system does not have at a scale that matters. With the lock and the on-event-loop blocking left
> in place, the same `/health` timeouts and the same request queue would remain, now waiting on a
> FastAPI/psycopg call instead of a SQLite call.

That is the sharp distinction the brief asked for:

* **"Postgres fixes the app's global lock" — false.** The lock is entirely inside the application;
  the engine is downstream of it.
* **"Postgres fixes SQLite's single-writer serialisation" — true in principle, but not the observed
  fault.** It buys concurrency only for writers that the app currently lets run concurrently, which
  is approximately none, because `_db_lock` serialises them first. It would only pay off *after*
  (1) `_db_lock` is removed/replaced with a real connection pool, and (2) blocking DB work stops
  running inline on the event loop (move to `run_in_threadpool`/`anyio.to_thread`, or an async
  driver), and (3) cron/cross-process writers are accounted for.

**Migration cost, if it were ever done:** high and structural. 231 tables, 2 031 raw-SQL call
sites, 147 `AUTOINCREMENT`s, 25 `INSERT OR REPLACE` + 38 `INSERT OR IGNORE` upserts, 248
`strftime(` + 201 `datetime(` SQL expressions, 80 `PRAGMA`s (`table_info`, `journal_mode`,
`foreign_keys`, `wal_checkpoint`, …), `sqlite3.Row`, `check_same_thread`, `mode=ro` URI usage,
WAL/checkpoint behaviour, and 3 FTS5 virtual tables with **no direct PostgreSQL equivalent**
(they would need `tsvector`/`pg_trgm`/an extension plus query/result rewrite — `MATCH` is not
translatable one-to-one). This is a data-access-layer rewrite, not a `DATABASE_URL` change.

**Recommended order (reasoned verdict):** fix the application first, where the fault is and where
the fix is cheap. Then, and only if cross-process write concurrency is still the limit, evaluate
Postgres on its own merits.

---

## 6. If you want the immediate win (not done — out of scope under the rules)

These are the changes the evidence points to, listed for the follow-up, **not performed here**
(the brief forbids config/code/DB changes and restarts):

1. Do not hold `_db_lock` across multi-query reads. `capture_freshness()` is the clearest offender:
   it should read each source under its own short lock (or read a materialized/cached snapshot),
   not one lock over ~12 scans.
2. Stop running blocking DB work inline in `async def` handlers. `comms_freshness()` and
   `comms_active_phones()` should be `def` (Starlette offloads those to the threadpool) or wrap the
   body in `run_in_threadpool` — every `comms_freshness()` call currently freezes the whole event
   loop.
3. Return `capture_freshness()` to a background/cached producer (it is already an autopilot
   concern) instead of an on-demand HTTP path that anyone/anything can trigger.
4. Reduce the 544 `with _db_lock:` sites on read paths; SQLite WAL already permits concurrent
   readers. Keep the lock only for the connection-dict mutation, which is what `_get_conn`'s own
   comment says it was meant for (`database.py:1085`).

---

## 7. The prior evidence, re-measured

| prior claim | this session's measurement |
|---|---|
| 71 contended waits in 30 min, ~2026-10-12 04:13Z | **71** in the rolling window `04:00:10Z → 04:30:10Z` (max over all windows) |
| `"db check timed out (lock contention)"` seen at least once | **199** occurrences in the journal window |
| 2 real `database is locked` in 19 h | **12** in ~38 h (same order) |
| 36 threads on one PID | `TasksCurrent=46` OS tasks / 13 Python threads on PID 1084 (the old 36-thread probe storm predates the single-flight `/health` fix) |
| busy_timeout 6 s fails, 25 s succeeds | not re-run — I did not execute a write-lock probe (see §6/§8); the engine lock is not the limiter anyway (12 events) |

---

## 8. Commands and scripts (reproducibility)

```bash
# target access (from zabz-tech-linux)
ssh -i ~/.ssh/id_ed25519_hetzner root@178.156.194.1 '...'

# lock definition / acquisitions
grep -n '_db_lock\s*=' /opt/company/app/database.py
grep -rIo 'with _db_lock' /opt/company/app --include='*.py' | wc -l
grep -c 'with _db_lock' /opt/company/app/database.py
grep -rIo '_db_lock.acquire' /opt/company/app --include='*.py' | wc -l

# unit / process
systemctl cat company-api
systemctl show company-api -p MainPID -p TasksCurrent -p NRestarts
ps -eo pid,ppid,nlwp,user,etimes,rss,%cpu,cmd | grep -E 'uvicorn|company-api'

# holder capture (py-spy installed under /tmp only)
/opt/company/.venv/bin/pip install --prefix=/tmp/pyspy --no-cache-dir py-spy
( curl -s -o /dev/null http://127.0.0.1:8002/api/v1/comms/freshness ) &
sleep 1
/tmp/pyspy/bin/py-spy dump --pid 1084

# journal counts (window 2026-10-11T00:00:22Z .. 2026-10-12T13:59Z)
journalctl -u company-api --no-pager | grep -c '_db_lock contended'      # 616
journalctl -u company-api --no-pager | grep -c 'Health DB probe timed out' # 199
journalctl -u company-api --no-pager | grep -c 'database is locked'        # 12

# max 30-min rolling window
journalctl -u company-api --no-pager -o short-iso | grep '_db_lock contended' \
  | awk '{print $1}' | cut -c1-19 | sort   # then rolling sum in python

# resource layers
nproc; free -h; uptime; vmstat 1 5; iostat -x 1 2; df -h /root

# postgres-surface counts
cd /opt/company/app
grep -rIl 'import sqlite3' --include='*.py' . | wc -l
grep -rIo '\.execute(' --include='*.py' . | wc -l
grep -rIo 'PRAGMA [A-Za-z_]*' --include='*.py' . | wc -l
grep -rIoi 'fts5' --include='*.py' . | wc -l
grep -rIo 'AUTOINCREMENT' --include='*.py' . | wc -l
grep -rIo 'INSERT OR REPLACE' --include='*.py' . | wc -l
grep -rIo 'strftime(' --include='*.py' . | wc -l

# schema census (read-only)
/opt/company/.venv/bin/python - <<'PY'
import sqlite3
con = sqlite3.connect('file:/root/authority.db?mode=ro', uri=True)
q = lambda s: con.execute(s).fetchone()[0]
print("tables   =", q("select count(*) from sqlite_master where type='table'"))
print("views    =", q("select count(*) from sqlite_master where type='view'"))
print("indexes  =", q("select count(*) from sqlite_master where type='index'"))
print("triggers =", q("select count(*) from sqlite_master where type='trigger'"))
print("fts5 =", [r[0] for r in con.execute(
    "select name from sqlite_master where lower(sql) like '%using fts5%'")])
PY
```

### Load-test script (`/tmp/loadtest_182.py`)

```python
import json, statistics, threading, time, urllib.request, sys
BASE = "http://127.0.0.1:8002"
PATH = sys.argv[1] if len(sys.argv) > 1 else "/api/v1/comms/active-phones"
ROUNDS = 6
LEVELS = [1, 4, 8, 16, 32]

def one(barrier, lat, errs):
    try: barrier.wait(timeout=60)
    except Exception: pass
    t0 = time.perf_counter()
    try:
        with urllib.request.urlopen(BASE + PATH, timeout=180) as r: r.read()
        lat.append((time.perf_counter() - t0) * 1000.0)
    except Exception as e:
        errs.append(type(e).__name__ + ": " + str(e)[:80])

def level(c):
    lat, errs, walls = [], [], []
    for _ in range(ROUNDS):
        b = threading.Barrier(c)
        ts = [threading.Thread(target=one, args=(b, lat, errs)) for _ in range(c)]
        t0 = time.perf_counter()
        for t in ts: t.start()
        for t in ts: t.join()
        walls.append((time.perf_counter() - t0) * 1000.0)
    lat.sort()
    pct = lambda p: lat[min(len(lat)-1, int(round((p/100.0)*(len(lat)-1))))] if lat else None
    return {"concurrency": c, "rounds": ROUNDS, "requests": len(lat), "errors": len(errs),
            "p50_ms": round(pct(50),1), "p95_ms": round(pct(95),1),
            "max_ms": round(max(lat),1) if lat else None,
            "mean_ms": round(statistics.mean(lat),1) if lat else None,
            "round_wall_mean_ms": round(statistics.mean(walls),1)}

print(json.dumps({"path": PATH, "host": "secratary-cloud",
                  "started": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}))
for c in LEVELS: print(json.dumps(level(c)), flush=True)
```

### AST scan (`/tmp/scan_lock_io.py`)

Walks every `ast.With` whose context is `_db_lock`, then reports calls whose dotted name is a
network client (`requests`, `httpx`, `urllib`, `socket`, `subprocess`, `paramiko`, `boto3`,
`openai`, `anthropic`, `aiohttp`, `twilio`, `dialpad`, …) or a file-IO bound method. Result:
1 hit total (`services/dialpad_webcrawler.py:4702 fp.write_bytes`).

---

## 9. Things I deliberately did not do

* No `PRAGMA`-write / `BEGIN IMMEDIATE` / `VACUUM` / integrity-check probe against
  `/root/authority.db`. The only DB access was one `mode=ro` `sqlite_master` census. The engine
  lock is demonstrably not the limiter (12 events), so the write-probe risk was not worth taking.
* No service state change of any kind, no config edit, no code edit, no package install outside
  `/tmp`.
* No load test at concurrency higher than 32, and no sustained test. The event-loop test used 16
  short reads; the full matrix is 6 rounds/level and completed with **0 errors**.
* I did not investigate the 842 `closed_on_handout` / 152 `closed_while_owner_alive` contention
  rows in `error_log` (`error_type='db_contention'`) beyond noting they are a *separate*
  connection-lifecycle defect, not the lock queue. They are worth a follow-up doc of their own.
