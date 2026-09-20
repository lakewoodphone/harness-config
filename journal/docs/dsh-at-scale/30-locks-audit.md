# 30 — Locks audit: the journal lock, the SQLite locks, and the exact races

Audit host: **ZABZ-YOGA** (Windows laptop), 2026-09-15 22:16–22:52 EDT, judged *under load*:
three to four concurrent agent sessions were writing the journal during the audit
(observed live: `journal.py append` PIDs 6976, 14268, 31876, 41584, 42088, plus two
`journal.py search` processes). Read-only except the two commands the brief sanctioned
(`check`, `doctor`) and this document.

Provenance of every reading: shell timings and file stats were taken on ZABZ-YOGA in the
window above; SQLite readings are from **this host's** `personal-secretary-mvp\data\`
copy, which is *not* the authority — this copy has **182** tables and no
`owner_decision_queue`; the authority (`secratary`) has 203 tables and owns that table.

---

## 0. The headline (measured, not inferred)

While this audit ran, a real fleet append held the journal lock for **89 seconds and
counting**, and the audit's own `journal.py check` was **killed by the harness at 120 s**:

```
22:47:55  lock: 'append 42088@zabz-yoga:1789526758'     (pid 42088 dead by 22:48:40)
22:48:40  lock: 'append 41584@zabz-yoga:1789526822'   held ~98 s
22:49:31..22:50:21  lock: 'append 6976@zabz-yoga:1789526932'   held 39 s -> 89 s (still held)
22:51:06  lock: 'append 31876@zabz-yoga:1789527027'   held ~40 s
22:51:13  lock: 'append 14268@zabz-yoga:1789527068'   held ~5 s -> 36 s, FREE at 22:51:49
```
and, from the same shell:

```
journal.py next-id lessons --no-fetch   -> 11,417 ms   (stderr: "journal: cache is stale and
                                           locked by append 42088@zabz-yoga:1789526758 —
                                           answering from entries/")
journal.py check --quiet                -> [timed out after 120000ms]
```

So: the journal's critical section is **40–100 s under normal fleet load**, not "well under a
second" as `journal.py:2467` assumes, and `LOCK_WAIT_SEC = 240` (`journal.py:142`) is larger
than the harness's 120 s foreground kill. The reported symptoms (a lock held, a stale break,
a 120 s timeout) are all reproducible and all present in the code below.

---

## 1. The journal tool and its lock

File: `C:\Users\ezabz\code\harness-config\journal\tools\journal.py` (3762 lines, stdlib only).
State dir: `C:\Users\ezabz\code\harness-config\journal\` with `state\`, `index\`, `entries\`.

### 1.1 Lock implementation, exactly

| Property | Value | Where |
|---|---|---|
| Path | `JOURNAL/.lock` = `journal\.lock` | `journal.py:134` (`LOCK_NAME = ".lock"`) |
| Create | `os.open(str(lock), os.O_CREAT \| os.O_EXCL \| os.O_WRONLY)` | `journal.py:2524` |
| Content | `"<command> <pid>@<host>:<epoch>\n"` — plain text, v1-compatible | `journal.py:2519` |
| Release | read content, `if token and token in held: lock.unlink()` | `journal.py:2558-2569` |
| Staleness | `age > LOCK_STALE_SEC (600)` **or** holder pid dead on this host | `journal.py:2534`, rule in `_lock_holder_is_dead` `2464-2504` |
| Liveness probe | Windows: `OpenProcess(0x1000, …)` handle test; POSIX: `os.kill(pid,0)`; other host ⇒ "unknown ⇒ not dead" | `journal.py:2482-2504` |
| Retry | `time.sleep(0.05)` fixed, no jitter, until `deadline = now + 240 s` | `journal.py:2521, 2546-2548` |
| On wait exhaustion | prints `REFUSING: another session holds the journal lock …` and the process exits **3** | `journal.py:2549-2552`, `3750-3753` |
| On stale break | prints `journal lock is stale (<why>, held by <token>); breaking it`, then `lock.unlink()`, then `continue` | `journal.py:2540-2545` |
| Who takes it | only `MUTATING_COMMANDS = {append, import-legacy, migrate-v2, dedupe, repair-ids, resolve, state, questions, gc-legacy, index}` | `journal.py:145-146`, `3750` |

The atomic-create half is correct: `O_CREAT|O_EXCL` is `CreateFile`/`CREATE_NEW` on Windows
and fails atomically against a concurrent creator. The whole race is in the **break path**,
which is `unlink` on a *path*, based on a *content read taken earlier*.

### 1.2 How two processes can both believe they hold the lock (the race, precisely)

`journal.py:2528-2545`:

```python
except FileExistsError:
    try:
        age = time.time() - lock.stat().st_mtime
        held = _rl(lock).strip()            # (A) read the holder
    except OSError:
        age, held = 0.0, "(unreadable)"
    if age > LOCK_STALE_SEC or _lock_holder_is_dead(held):   # (B) decide it is stale
        note("journal lock is stale (%s, held by %s); breaking it" % (why, held))
        try:
            lock.unlink()                   # (C) unconditional delete of whatever is at that path
        except OSError:
            pass
        continue                            # (D) create our own and proceed
```

Interleaving, with the exact line that makes it wrong:

1. T0 — `.lock` exists, content is a token whose pid is gone (killed session). *(This state is
   created on this host routinely; see §1.5.)*
2. T1 — process **A** hits `FileExistsError`, reads `held` at **(A)**, decides stale at **(B)**.
3. T2 — process **B** hits `FileExistsError`, reads the same `held`, decides stale at **(B)**.
4. T3 — **A** executes `unlink()` at **(C)**, `continue`s, and creates its own lock at `2524`
   with `O_EXCL`; **A now holds the lock and is inside the critical section.**
5. T4 — **B** executes `unlink()` at **(C)** — this deletes **A's live lock**, because `unlink`
   compares nothing. **B** then creates its own lock at `2524` (the path is free) and is also
   inside the critical section.
6. Result: **two writers, one tree.** Both run `absorb_all` → `max_number` → `allocation_ceiling`
   → `atomic_write` → `rebuild_cache` concurrently.

`release_lock` (`2558-2569`) contains the correct compare-and-swap idea (it refuses to delete a
lock whose token is not its own), but it only protects *release*; the break path bypasses it.
A's later release is therefore a no-op (good — no extra damage), which is precisely why the
failure is silent: nothing reports that mutual exclusion was lost.

This is the same defect class the file itself dates: `journal.py:136-144` and `2549-2551`
("Two writers is what created 161 collided ids on 2026-09-14"). Measured consequences of two
writers here:

- **id collisions** — the id is `max(entries/, index, log/**, flats, git refs) + 1`
  (`allocation_ceiling` `2625-2635`, `max_number` `2572-2602`, `git_max` `2654-2691`), a
  read-then-write with no compare-and-swap. Two writers read the same ceiling and both write
  `X(N+1).md`; the loser's `path.exists()` check at `2765` only helps if it runs *after* the
  other's `atomic_write` at `2792`.
- **lost alias rows** — `record_alias` (`2824-2837`) is read-modify-write of the whole
  `index/aliases.tsv`; two writers drop one another's rows.
- **index/entry divergence (the subtle one)** — `ensure_cache()` (`1057-1081`) is called by
  *every read* and rebuilds the cache **without taking the lock** when `lock.exists()` is false
  at the instant it checks (`1068-1069`). A reader can therefore be a writer: it scans
  `entries/` at time t0, a real append writes a new entry at t1 > t0 and rebuilds at t2,
  and the reader then writes its *older* row set to `index/entries.tsv` plus a `stamp.json`
  whose `tree_signature()` was computed at the **end** of its rebuild (`990-1031`, `1001`).
  `cache_fresh()` (`1044-1054`) compares only the tree signature, so it then reports **fresh**
  while `entries.tsv` is missing the new entry — a silently invisible entry until the next
  tree change or `journal.py index --force`. No files are torn (`atomic_write` is tmp +
  `os.replace`, `219-241`), so this is a lost update, not corruption.

### 1.3 Can a crash corrupt an entry or the index?

- **Entry files: no.** Every entry write is `atomic_write` (tmp `<name>.tmp<pid>` in the same
  dir, then `os.replace`) — `journal.py:219-241`, used at `2792`, `3102`, `3455`, `2272`. A
  killed writer leaves either the old file or the complete new one.
- **The index: inconsistent, never unreadable, and always regenerable.** `rebuild_cache`
  rebuilds `entries.tsv`, `journal.db` (sqlite + FTS5 on a *temp* file, swapped in by
  `os.replace` at `979`) and `stamp.json` from `entries/` (`990-1031`). A hard kill inside
  `_write_db` leaves the temp file behind — **observed right now**:
  `journal\index\.journal.db.tmp35748` (1,024,000 B, 21:31:57) and
  `.journal.db.tmp35748-journal` (26,112 B, 21:31:54) — the residue of a writer killed at
  21:31. Harmless to readers (the live `journal.db` is untouched) but it is direct evidence
  that writers *are* being killed mid-write on this host.
- **A crash cannot duplicate an id; only concurrency can** — the allocator bumps past any
  existing path with different content (`2765-2787`) and never renumbers downwards
  (`allocation_ceiling` docstring `2625-2632`).
- **A crash between append and rebuild** (`2792` → `2795`) leaves a stale cache, which the next
  read detects via `tree_signature` and rebuilds — correct and by design.

### 1.4 What every append does that is slow (measured)

`cmd_append` (`2709-2807`), in order, all inside the global lock:

| Step | Code | Cost (measured 22:16–22:51, under load) |
|---|---|---|
| 1. `absorb_all(kinds=[kind], apply=True)` — scan `log/**` + the flat files, possibly write | `2738`, `3000+` | part of the 40–100 s critical section |
| 2. `git_max(kind, fetch=True)` unless `--no-fetch`: `git fetch --quiet --all` (network, 25 s timeout), `git rev-parse` (15 s), and **two** `git grep -h -E` over the whole repo (60 s each) | `2664-2691`, `2750-2752` | `git grep` = 1.25 s + 2.30 s; `git rev-parse` = 0.58 s; network leg `git ls-remote` = 3.30 s; **`next-id --no-fetch` end-to-end = 11.4 s under load** |
| 3. `atomic_write` the entry | `2792` | ms |
| 4. `rebuild_cache()` — `load_entries()` over 1284 files, rewrite `entries.tsv` (265 KB), **full rebuild of `journal.db` (6,376,472 B, sqlite + FTS5 over 1284 entries)**, rewrite `stamp.json` | `2795`, `990-1031`, `937-987` | the dominant remaining cost |

So each append rewrites the **entire** index and, without `--no-fetch`, also does a network
fetch. All four live appends observed during this audit **did** pass `--no-fetch`, so the
network leg is currently avoided in practice — but nothing enforces it: `--no-fetch` is opt-in
per call site (`journal.py:3671, 3714`), and passing it is the only thing preventing a 25 s
network call inside the critical section.

`journal.py costs` measured **14.6 s**; `journal.py doctor` 3.65–6.31 s (it calls `git rev-parse`
**and** `git ls-remote`, `2443-2457`); `status` 3.1–4.3 s; `list --kind lessons --limit 3` 1.66 s;
`newest handoff 1` 1.78 s; `check` 42 s on a fresh cache and **>120 s (killed)** when a
concurrent append held the lock and the cache was stale.

### 1.5 The two amplifiers that turn a slow lock into the reported incidents

**(a) A read command takes the write lock and then talks to another host.**
`cmd_status` calls `_maybe_refresh_questions` (`journal.py:1412`). If the mirror
`state/owner-questions.md` is older than 60 minutes, that function spawns
`journal.py questions` as a subprocess (`804-831`). `questions` is in `MUTATING_COMMANDS`
(`145-146`), so it **takes the global write lock**, and inside it, `_queue_from_authority`
(`1966`, `2013-2038`) runs

```python
subprocess.run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=8", "secratary-ts",
                "python3 ~/bin/owner-queue.py list --all --json"], …, timeout=45)
```

i.e. **the journal write lock is held across a network round trip to another machine, up to
45 s, triggered by a read.** Two sessions that both run `status` can therefore produce lock
contention on their own, with no writer involved. Observed: `state\owner-questions.md` was
regenerated at 22:24:34 during this audit's own read timings.

**(b) The wait budget exceeds the harness kill.** `LOCK_WAIT_SEC = 240` (`142`) versus the
harness's 120 s foreground timeout. A writer that queues behind two ~60 s appends is killed
mid-wait — harmless — but a writer killed *while holding* the lock leaves a token whose pid is
dead, which is exactly the input to the race in §1.2, and the code's own fast path
(`_lock_holder_is_dead`, `2464`) makes that token breakable **immediately**, so the break path
runs far more often than the 600 s age rule suggests. Observed at 22:48:40: the lock named
`append 42088@…:1789526758` and pid 42088 was already gone.

**(c) An interrupted reader can leave an unparseable-or-empty lock.** A kill between
`os.open` (`2524`) and `fh.write` (`2526`) leaves a **zero-byte** `.lock`. `_rl` returns `""`,
`_lock_holder_is_dead` returns `False` (its regex `(\d+)@([^:]+):` cannot match `""`,
`2476-2478`) and the age is ~0, so every writer queues for the full **240 s** and then exits 3.
That is a lock with no visible holder and no fast way out — the "tool call that appears to hang".

---

## 2. The owner decision queue and the company database

### 2.1 Where SQLite is opened

Repo: `C:\Users\ezabz\code\personal-secretary-mvp`. 452 `sqlite3.connect` / PRAGMA hits across
the repo; the ones that matter for contention are the ones that touch one shared file.

**Databases actually written by this host's copy** (read read-only at 22:44 EDT):

| File | Size | Header (`write_ver@18` / `read_ver@19`) | `journal_mode` | Tables |
|---|---|---|---|---|
| `data\secretary.db` | 504,360,960 B (+ `-wal` 41,200,032 B, `-shm` 98,304 B) | 2 / 2 | `wal` | 182 (authority: 203) |
| `data\family_chat.db` | 53,248 B | 2 / 2 | `wal` | 6 |
| `data\phone_chat_history.db` | 20,480 B | 2 / 2 | `wal` | 3 |
| `data\test_secretary.db`, `tmp_test_client.db`, `unused.db` | — | — | — | test residue |

**Settings actually in effect** (fresh read-only connection, same read):
`journal_mode = wal` (persisted in the file header — bytes 18/19 = 2 — so it survives any
connection); `page_size = 4096`; `wal_autocheckpoint = 1000`; `journal_size_limit = -1`;
`foreign_keys = 0`. `wal_autocheckpoint` and `journal_size_limit` are **per-connection**, not
persisted: the app sets `wal_autocheckpoint=10000` and `journal_size_limit=67108864`
(`app\database.py:317-318`), while any other script that connects without them gets the
defaults shown above — i.e. constant 4 MB checkpoints and a WAL that is never truncated.

**The app's connection policy** — long-lived, per-thread, one profile:

```python
key = f"{db_url}:{threading.get_ident()}"                    # database.py:257
...
conn = sqlite3.connect(str(db_path), check_same_thread=False, timeout=10.0)   # 301-305
conn.execute("PRAGMA journal_mode=WAL")                       # 307
conn.execute("PRAGMA foreign_keys=ON")                        # 308
conn.execute("PRAGMA busy_timeout=10000")                     # 309
conn.execute("PRAGMA synchronous=NORMAL")                     # 310
conn.execute("PRAGMA cache_size=-64000"); temp_store=MEMORY   # 311-312
conn.execute("PRAGMA wal_autocheckpoint=10000")               # 317
conn.execute("PRAGMA journal_size_limit=67108864")            # 318
```

Connections are cached in `_connections` for the **life of the process** (`22-23`, `321-323`)
and only dropped by `close_db_connections` (`326-351`) or when a probe `SELECT 1` fails
(`270-283`). `_db_lock` is a process-local `RLock` that guards the *dict*, not every SQL call —
the module is explicit that it is bookkeeping only, `dsh_session_ingest.py:61-64` — and
`sqlite3.connect()` is deliberately performed **outside** it (`292-305`).

**Long-lived vs per-call:** the API process keeps one connection per (db, thread) forever; every
CLI/script in `scripts\` and `app\services\` opens a fresh per-call connection with its own
ad-hoc pragmas — e.g. `scripts\ps_mcp_server.py:118`, `scripts\ai_cost_tracker.py:105,138,150,162,197,742,797`,
`app\services\semantic_memory.py:581,933`, `app\services\outbound_buffer.py:100,162,188,310,341` —
most of them with no `busy_timeout` at all (Python's default handler is the `timeout=` value,
5 s). `app\services\dsh_session_ingest.py:70` sets `busy_timeout = 30000`;
`app\services\plaid_service.py:112-116` sets WAL + 10 s; `app\family_chat\db.py:91-95` sets WAL + 30 s.

### 2.2 `owner-queue.py`

`C:\Users\ezabz\bin\owner-queue.py` **does not exist on this host** (`C:\Users\ezabz\bin` is
absent), matching the documented fact that it lives on the authority only. The copies on this
machine are `C:\Users\ezabz\code\harness-config\scripts\owner-queue.py` (9761 B) and
`C:\Users\ezabz\code\_scratch\yocheved\mac-pack\scripts\owner-queue.py`.

```python
DEFAULT_DB = os.environ.get("OWNER_QUEUE_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db")   # :49-51
def connect(path):                                        # :82-87
    con = sqlite3.connect(path, timeout=20)
    con.row_factory = sqlite3.Row
    con.executescript(SCHEMA)      # CREATE TABLE IF NOT EXISTS + CREATE INDEX
    con.commit()
    return con
```

Two concrete defects:

1. **A read takes the database's write lock.** `executescript(SCHEMA)` runs on **every**
   invocation, including `next`, `list` and `stats` (`:274-277`). `CREATE TABLE IF NOT EXISTS`
   and `CREATE INDEX IF NOT EXISTS` are DDL, i.e. writes: each `owner-queue.py next` opens a
   write transaction on the 500 MB `secretary.db` shared with 18 agents ticking all day. The
   only protection is `timeout=20` (`:83`); no `busy_timeout`, no WAL pragma (WAL comes from the
   file header, so that part is fine), no `BEGIN IMMEDIATE`.
2. **The Windows copy points at a Linux path.** With `OWNER_QUEUE_DB` unset, `DEFAULT_DB` is
   `/home/zabz/...`; on Windows that resolves under the current drive root
   (`C:\home\zabz\...`, which does not exist yet), and `sqlite3.connect` would *create* a
   brand-new empty database there and report an empty queue rather than refusing. Evidence that
   this is the wrong store on this host: querying `owner_decision_queue` in this host's
   `secretary.db` read-only fails with `no such table: owner_decision_queue`.

Also present: `scripts\patch-owner-queue-busy.py`, `scripts\port-dedup-owner-queue.py`,
`scripts\collapse-owner-queue-duplicates.py` — the contention has already been patched around
more than once.

### 2.3 The concrete cause of SQLite lock contention

SQLite permits **exactly one writer per database file**. Here one 500 MB file
(`data\secretary.db`) is written by: the FastAPI process (autopilot + ~12 subsystems + HTTP
handlers + agent ticks), `dsh_session_ingest` backfills, `ai_cost_tracker`, `outbound_buffer`,
`semantic_memory`, the CLI scripts, the MCP server, and (on the authority) `owner-queue.py`'s
per-invocation DDL. There is no single-writer queue and no serialisation beyond the engine's own
write lock, and `_db_lock` is per-process so it does nothing across processes.

The **specific stall mechanism** (the difference between "slow" and `database is locked`) is the
**deferred read-then-write upgrade**, documented and fixed in this repo at
`app\services\dsh_session_ingest.py:242-255`:

> Python's sqlite3 opens a deferred transaction on the SELECT above. When the next statement is a
> write, SQLite must upgrade a read transaction to a write one — and if any other connection
> committed in between … the upgrade fails with SQLITE_BUSY **immediately**. `busy_timeout` cannot
> help, because waiting cannot make a stale snapshot current.

Measured there on 2026-09-11: four ingest backfills died, `error_log` rows 809–812. On this
host's copy the corroborating row count is small — `error_log` holds 169 rows and exactly **1**
row matching `database is locked` (id 1) — so the 809–812 evidence is the authority's, not this
laptop's; stated here so the numbers are not mixed.

Wait budgets in effect, per connection: 10 s (app, `database.py:304/309`), 30 s
(`dsh_session_ingest.py:70`), 20 s (`owner-queue.py:83`), 5 s (Python default, any
script that passes no `timeout`). When the budget expires the caller sees `SQLITE_BUSY`/"database
is locked" and, depending on the call site, either a 500, a failed agent tick, or a retry
(`database.py:43-69` `commit_retry`, `354+` `_retry_db_op`, `app\services\outbound_buffer.py`).
Nothing deadlocks — SQLite has no lock ordering to invert — so every "stall" is a *wait*, and the
only unbounded ones are those held across slow work by a long-lived connection with an open
read transaction or an open write transaction.

---

## 3. Other shared lock files in this harness

Searched `harness-config\scripts\` and `harness-config\` code files
(`*.ps1,*.sh,*.py,*.mjs,*.js`) for `flock`, `msvcrt`, `O_EXCL`, `CREATE_NEW`, `LockFile`,
`filelock`, `Mutex`/`Global\`, `mkdir`-as-mutex, `.lock`. Twelve matches, all listed:

| Path | Mechanism | Purpose | Notes |
|---|---|---|---|
| `journal\.lock` | `os.open(O_CREAT\|O_EXCL)` + unlink | serialise journal mutations | `journal.py:134, 2519-2569` — the only file mutex in the tree; broken (§1.2) |
| `journal\tools\archive\journal-v1.py:1221,1245` | same path, same shape | v1 of the same lock | interop is why the path/content is frozen |
| `_scratch\journal_v1.py:1221,1245` | same | v1 scratch copy | same tree, same lock name — a third potential breaker |
| `scripts\comms-refresh.py:46,114,130` | `fcntl.flock(fh, LOCK_EX\|LOCK_NB)` | one comms index refresh at a time | **POSIX-only** (imports `fcntl`, cannot run on Windows); correct design — the kernel releases it if the process dies, so no staleness rule is needed |
| `scripts\port-dedup-owner-queue.py:34,132` | (false positive) `CREATE_NEW` is a SQL string | migration patch | not a lock |

No `msvcrt.locking`, no `filelock`, no named mutex (`[System.Threading.Mutex]`, `Global\`), no
`LockFile`/`LockFileEx`, no `mkdir`-as-mutex, and **no `.lock`/`.mutex` files anywhere under
`harness-config` (depth-3 sweep returned none) or under `~\.dsh`**. Git worktrees used by
`scripts\agent-fleet.ps1` provide *isolation*, not locking.

There is also **no queue and no single-writer notion** anywhere in the journal tool: one global
lock, no FIFO, no fairness, no ticket. Waiters spin at a fixed 0.05 s (`2547`) and the fastest
wakes first, so under a fleet the lock is effectively random-ordered.

---

## 4. Collision history and the current health of the tree

Commands run (read-only as specified; note they do write — see below):

```
$ python journal.py check      # 22:16:00 -> 22:16:42 (42 s), exit 0
-- 0 error(s), 51 warning(s), 78 info
WARN  alias W26 -> W67 (wins): canonical id is missing
WARN  H83 (handoff) has an empty body
WARN  dangling ref D103 (cited by D104) — nothing in entries/ has that id
  ... 20 shown, "31 more warning(s)"
INFO  entries/decisions/D105.md: heading carries the legacy id D67; this entry is filed as D105
  ... "68 more info line(s)"

$ python journal.py doctor     # 22:16:42 -> 22:16:45 (3.3 s), exit 0
root            C:\Users\ezabz\code\harness-config\journal
format          2 (entries/ present: True)
entries         1276 file(s), 1276 in the last cache build
cache           fresh · stamp 2026-09-16 02:07 UTC
legacy drift    0 — {}
lock            free
writable        True
python/sqlite   3.12.10 / 3.49.1 · fts5 yes
git             @7c16260, origin reachable
```

- **No duplicate ids today**: `check` exits 0 with 0 errors. The reachable forms of the old
  defect are present as warnings only (missing canonical for `W26 → W67`, 51 dangling refs).
- **`index\aliases.tsv` history** (393 rows): 390 are
  `same entry absorbed by identity, not by bytes`, 2 are `identity duplicate inside entries/`,
  and **zero** rows whose reason mentions a collision — the 161 collisions of 2026-09-14 were
  renumbered/absorbed (`repair-ids`, `dedupe`) rather than preserved as aliases.
- **Hard-kill residue in the index**: `index\.journal.db.tmp35748` (1,024,000 B, 21:31:57) and
  `index\.journal.db.tmp35748-journal` (26,112 B, 21:31:54) — a writer killed mid-`_write_db`
  (`237:940`) while holding the lock. This is the physical trace of the mechanism that produces
  orphan locks.
- **Live concurrency during the audit**: entries grew 1276 → 1284 in 35 minutes
  (`L1692.md` 22:46:37 … `L1695.md` 22:51:30) across at least four sessions.
- **The "read-only" commands are not read-only.** `check` rewrites `index\stamp.json`
  (`journal.py:2205`) — mtime moved to 22:19:58 during this audit — and `status`/reads can
  regenerate `state\owner-questions.md` through the `questions` subprocess (`1412`, `2008`) —
  mtime moved to 22:24:34. Disclosed because the brief said read-only; nothing else was written
  by me except this document.
- **Degraded-read evidence**: at 22:47 the cache was `STALE` and locked, so `status`, `doctor`
  and `next-id` all answered `from entries/`: `status` 3.1 s, `doctor` 3.65 s, while
  `check` (full-tree parse, 51 warnings, drift scan) exceeded 120 s and was killed.
  Two `python.exe` processes matching journal invocations were still alive after the harness
  reported the timeout, i.e. the 120 s kill is not a guarantee that the work stopped.

---

## 5. Failure modes

| # | Scenario | What actually happens today | Consequence | Minimal fix |
|---|---|---|---|---|
| F1 | Writer killed by the 120 s harness cap while holding the lock | token names a dead pid (observed: `append 42088` at 22:48:40); next writer's `_lock_holder_is_dead` returns True immediately and breaks it (`2540`) | the stale-break path runs often, enabling F2 | keep waits *below* the harness cap (≤45 s) and make the break a compare-and-swap (§6) |
| F2 | Two writers see the same stale lock | both `unlink()` at `2542`; A creates, **B deletes A's live lock**, both enter | two writers → id collisions, lost alias rows, `entries.tsv` missing a just-written entry while `stamp.json` says fresh | CAS break: one atomic `os.replace` winner, then verify the moved content |
| F3 | A live writer slower than `LOCK_STALE_SEC` (600 s) | the age branch at `2534` breaks the lock **without any liveness check** | two writers | probe liveness first; heartbeat `os.utime(lock)` every ~10 s while held |
| F4 | Crash between `os.open` (2524) and `fh.write` (2526) | zero-byte lock; not matchable as dead, not stale | every writer waits the full 240 s then exits 3 — a hang with no visible holder | treat an empty/unparseable lock as dead after a short grace (~5 s), or use an OS lock so this cannot exist |
| F5 | Waiting writer under fleet load | remaining wait can be 240 s (queue behind 40–100 s appends), harness kills at 120 s | apparent hang; killed process may survive (observed) | `LOCK_WAIT_SEC` ≈ 30–45 s + jittered backoff; exit 3 loudly; keep the mutation small |
| F6 | Read needs a fresh cache while a writer holds it | `ensure_cache` refuses and answers `from entries/` (`1057-1081`) | full parse per read: `status` 3–4 s, `check` >120 s, `costs` 14.6 s | bound the expensive reads; never rebuild the whole cache per read |
| F7 | `status` (a read) with a mirror older than 60 min | spawns `journal.py questions`, a **mutating** command that takes the lock and `ssh`es to `secratary-ts` (45 s timeout) under it (`1412`, `821-825`, `1966`, `2013-2038`) | reads cause writer contention; writers queue behind a network call to another host | refresh the mirror **outside** the lock (or under its own lock), and never ssh while holding |
| F8 | Reader rebuilds while a writer appends | reader scans entries, writer appends + rebuilds, reader writes its older `entries.tsv` + a *fresh-looking* `stamp.json` (`990-1031`, `1001`, `1044-1054`) | a new entry is invisible to every reader and `cache_fresh()` says fresh | make rebuilds lock-aware (take the lock, or refuse and answer from `entries/`) |
| F9 | Every append | 2 full-repo `git grep`s + full 6.4 MB `journal.db` rebuild, 40–100 s measured (`2664-2691`, `990-1031`, `2795`) | queueing, timeouts, killed writers | default `--no-fetch`; cache the git ceiling (already in `stamp.json:1011-1013`); update the index incrementally |
| F10 | `owner-queue.py next/list/stats` | `executescript(SCHEMA)` runs DDL on every call (`82-87`) | a read takes the 500 MB DB's write lock; contention with 18 ticking agents | gate the schema behind `PRAGMA user_version`; open read-only for `list`/`next` |
| F11 | Long-lived app connection with an open read txn | deferred→write upgrade returns `SQLITE_BUSY` immediately; `busy_timeout` cannot help (`dsh_session_ingest.py:242-255`) | failed ticks/backfills that look like lock contention but are transaction shape | `conn.commit()` before a write (the fix already in `dsh_session_ingest`); `BEGIN IMMEDIATE` for read-then-write |
| F12 | Scripts connecting without pragmas | `wal_autocheckpoint=1000`, `journal_size_limit=-1` (measured) on a 41 MB WAL | chatty checkpointing, WAL never truncated | one shared connect helper that always sets WAL, `busy_timeout`, `synchronous=NORMAL`, `journal_size_limit` |
| F13 | Windows copy of `owner-queue.py` run without `--db` | creates a phantom DB under `C:\home\zabz\...` and prints an empty queue | wrong store reports "nothing waiting on the owner" | make it refuse when `OWNER_QUEUE_DB` is absent and the default path does not exist |

---

## 6. A lock protocol that is correct here on Windows

### 6.1 Preferred: an OS lock (no staleness concept at all)

The kernel releases these on process death, which deletes F1–F4 in one stroke.

```python
import os, msvcrt, fcntl  # pick per platform, both are stdlib

fd = os.open(str(lock), os.O_CREAT | os.O_RDWR | getattr(os, "O_BINARY", 0))
if os.name == "nt":
    msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)        # non-blocking; raises OSError when held
else:
    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
os.ftruncate(fd, 0); os.write(fd, token.encode()) # keep the v1 text for humans/v1 readers
```
- `msvcrt.locking` needs ≥1 byte in the file to lock a region and is released automatically when
  the handle closes or the process dies.
- Retry with jitter — `time.sleep(random.uniform(0.05, 0.35))` — and a wait budget **below** the
  harness kill (45 s), then exit 3 as today.
- Release: unlock the byte range (`LK_UNLCK` / `LOCK_UN`), close, and unlink only if the content is
  still your token (the existing `release_lock` logic, `2558-2569`).
- Interop note: the byte lock is not mandatory against a *v1* process that only checks file
  existence, so keep the token file present and never break it by `unlink`.

### 6.2 Minimum-change alternative: make the break a compare-and-swap

If the file itself must remain the lock (v1 compatibility, `tools/archive/journal-v1.py:1245`),
replace `lock.unlink()` at `journal.py:2542` with a two-phase claim:

1. Read `(held_token, mtime)` and decide staleness — exactly as today (`2530-2534`).
2. **Atomically move it aside**: `os.replace(lock, lock + ".broken.<pid>.<rand>")`.
   Only one process can win this rename; a loser gets `FileNotFoundError` → loop and re-read.
3. **Verify what you moved**: read the moved file. If its content is **not** the `held_token` you
   judged stale, you have stolen a *live* lock — move it back (`os.replace` back to `lock` if the
   path is free; otherwise leave it aside and loop) and retry. This is the compare-and-swap: it is
   the check that `2558-2569` already performs in `release_lock`, applied to the break path.
4. Create your own lock with `os.open(..., O_CREAT|O_EXCL)` (`2524`), write the token, then **read
   it back** and confirm it is yours before doing any work.
5. Delete the aside file.
6. Add a heartbeat (`os.utime(lock)` every 10 s from a daemon thread while the mutation runs) so
   the 600 s age rule can never fire on a live writer (F3), and treat a zero-byte lock as dead
   after a 5 s grace (F4).

### 6.3 Can the journal adopt this with a small patch?

**Yes — one function plus two moves, no caller changes.**

- `acquire_lock` (`2507-2556`): ~25 lines become ~40 (rename-with-verification, jitter, heartbeat
  start, `LOCK_WAIT_SEC` lowered to ≤45 s). `release_lock` (`2558-2569`) already implements the
  ownership check and stays.
- `MUTATING_COMMANDS` (`145-146`), the `main()` dispatch (`3750-3757`) and exit code 3 are unchanged.
- Move the owner-queue mirror refresh **out** of the lock: `_maybe_refresh_questions` (`804-831`)
  should not spawn a `MUTATING_COMMANDS` subprocess from a read (`1412`); give `questions` its own
  lock file, or have the reader refresh the mirror asynchronously after answering.
- Bonus, cheap: make `--no-fetch` the default for `append` (F9) and have `ensure_cache`
  (`1057-1081`) take the write lock before rebuilding (F8).
- For SQLite the analogous discipline is not a mutex: `BEGIN IMMEDIATE` for any read-then-write,
  `busy_timeout` set on **every** connection, WAL + `journal_size_limit` in one shared connect
  helper, and the `owner-queue.py` schema bootstrap gated behind `PRAGMA user_version` so a read
  stops taking the write lock.

---

## 7. Measured timings (all on ZABZ-YOGA, 2026-09-15 22:16–22:52 EDT, 3–4 concurrent sessions)

| Measurement | Value |
|---|---|
| `journal.py status` | 3.1 s (stale cache, locked) / 4.25 s (fresh cache) |
| `journal.py list --kind lessons --limit 3` | 1.66 s |
| `journal.py newest handoff 1` | 1.78 s |
| `journal.py doctor` | 3.65 s / 6.31 s |
| `journal.py costs` | 14.62 s |
| `journal.py next-id lessons --no-fetch` | 11.42 s under active append load |
| `journal.py check` | 42 s (fresh cache) · **>120 s → killed by the harness** (stale cache + concurrent append holding the lock) |
| `git grep -h -E '^## L[0-9]+ '` (all refs) | 1.25 s |
| `git grep -h -E '^## L[0-9]+ ' HEAD` | 2.30 s |
| `git rev-parse --short HEAD` | 0.58 s |
| `git ls-remote --exit-code origin HEAD` (network leg of `fetch`) | 3.30 s |
| **Real append lock hold time** | 41 s (31876), 41 s (14268), ≥89 s (6976, still held), ≥98 s (41584) |
| Journal `.lock` staleness threshold / wait budget | 600 s / 240 s — the latter exceeds the 120 s harness kill |
| Journal tree growth during audit | 1276 → 1284 entries in 35 min |
| `index\journal.db` rebuilt on every append | 6,376,472 B |
| `data\secretary.db` / WAL / shm | 504,360,960 / 41,200,032 / 98,304 B |
| `check` result | 0 errors, 51 warnings, 78 info, exit 0 |
| `doctor` result | lock free, cache fresh, 1276 entries, drift 0, git @7c16260, exit 0 |
