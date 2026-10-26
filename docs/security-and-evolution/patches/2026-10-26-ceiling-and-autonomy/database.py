"""Persistent SQLite database for the secretary's memory, conversations,
tasks, and knowledge base.

This replaces the JSON-only memory with a real searchable database that
persists across restarts and supports efficient querying.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import sqlite3
import threading
import time
from collections import OrderedDict, deque
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from app.services.payment_card_redaction import redact_body_for_storage

_log = logging.getLogger(__name__)

_db_lock = threading.RLock()

# ── BOUNDED WAIT ON _db_lock (c10-lockfix, decided 2026-10-15) ───────────────
# `_db_lock` is documented as guarding only the connection cache, but ~200
# `with _db_lock:` blocks in this module (and several in main.py) also wrap real
# SQL, so a slow statement holds it. The wait on it was (2.0 s probe) + (acquire()
# with NO timeout): an unbounded acquire behind a bounded one. The caller looks
# protected and the worker is not -- and a thread parked there never comes back,
# so this leaks threadpool workers instead of slowing one query down.
#
# MEASURED, secratary-cloud. 2026-10-14 16:05:34Z the ingest path logged `_db_lock
# contended`; the process stopped answering every route at 16:05:51Z while systemd
# still reported `active (running)`, and was restarted by hand at 17:10:50Z (73
# minutes). A py-spy dump at 23:31:00Z caught one thread inside SQLite `execute`
# (this file, line 588) holding `_db_lock` -- it was
# services/dsh_session_ingest.py `_ingest_export_once` doing its FTS5 re-index --
# with 6+ threads parked on the acquire below. In the 24 h to 2026-10-15T00:21Z
# this unit logged 519 `_db_lock contended` warnings and 101 `Health DB probe
# timed out`, and it wedged at least three times that day.
#
# THE NUMBER, and it is not invented:
#   * 2.0 s is the probe this call site already used.
#   * 10 000 ms is what this module already declares as the app's willingness to
#     wait for SQLite itself (SQLITE_BUSY_TIMEOUT_MS, the W7 decision in the
#     "Bounded waiting" block above). A process-local lock held for a dict must
#     not be waited on for longer than that.
#   * 5.0 s is the value this estate already chose AND MEASURED for exactly this
#     line on 2026-09-28 (handoff H2789, lesson L2795: `PS_DB_LOCK_WAIT_S` = 5 s,
#     "health DB probe failures 32% -> 0%"). That fix never reached this checkout;
#     re-landing its value keeps its measurement applicable instead of replacing a
#     measured number with a fresh guess.
# Override with PS_DB_LOCK_WAIT_S. The TOTAL bounded wait is DB_LOCK_WAIT_S.
DB_LOCK_WAIT_S = max(0.1, float(os.environ.get("PS_DB_LOCK_WAIT_S", "5")))
# The first, short probe. Kept at the value this site has always used because the
# warning it emits is this estate's only instrumentation for in-process lock
# contention (519 occurrences in the 24 h measured above).
DB_LOCK_PROBE_S = 2.0
# How long a *read-only* /health probe may wait on SQLite itself. Deliberately
# under the caller's own 2 s budget, so the probe thread always returns before its
# caller gives up (which, in anyio's threadpool, it cannot force).
HEALTH_PROBE_BUSY_TIMEOUT_S = max(
    0.1, float(os.environ.get("PS_HEALTH_PROBE_BUSY_TIMEOUT_S", "1.5"))
)


class DBLockTimeout(sqlite3.OperationalError):
    """``_db_lock`` was not free within :data:`DB_LOCK_WAIT_S` seconds.

    Subclasses ``sqlite3.OperationalError`` and keeps the words "database is
    locked" in its message ON PURPOSE: the existing transient-lock plumbing
    (:func:`is_locked_error`, ``commit_retry``, the DSH-ingest retry loop) then
    treats a busy *process* the way it already treats a busy *database* -- retried
    on a bounded budget -- instead of as a brand-new error class no caller has ever
    seen. It is still a distinct type, so a caller can tell "a thread of this
    process is holding the connection-cache lock" from "SQLite refused the write".
    """


_connections: "OrderedDict[str, sqlite3.Connection]" = OrderedDict()

# (key, conn) pairs the prune pass has ALREADY evicted from the cache and that
# must be rolled back and closed OUTSIDE ``_db_lock``. conn.rollback()/close()
# release the SQLite write lock on a 27.6 GB authority.db and can block for
# seconds; the module docstring says _db_lock must never be held across a
# SQLite call.
_deferred_closes: "list[tuple[str, sqlite3.Connection]]" = []
# Item 168: leaked write transactions collected under _db_lock and rolled back
# after it is released. Rollback releases the SQLite WRITE lock and can block for
# seconds, so it must never run while the global connection-dict lock is held.
_deferred_reaps: "list[tuple[str, sqlite3.Connection, float]]" = []
# Last time each cached connection was handed to a caller (monotonic seconds). Kept
# in a separate dict so the cache key format ("url:thread_id") stays exactly what
# ``close_db_connections`` and existing tests match on.
_conn_last_used: dict[str, float] = {}
# When each cached connection was FIRST observed holding an open transaction
# (monotonic seconds). A transaction that stays open past LEAKED_TXN_TTL_S is a
# leak, not work in flight; this is how the cache tells the two apart without
# guessing. Set on the first ``_get_conn`` that sees ``in_transaction``; cleared
# as soon as a later call sees the transaction gone.
_conn_txn_since: dict[str, float] = {}

# ── Bounded waiting ──────────────────────────────────────────────────────────
# Every connection this module hands out waits this long for the SQLite write lock
# before raising "database is locked".
#
# DECIDED 2026-09-28 (W7): the value stays 10 000 ms. The brief is explicit that the
# busy_timeout is "already correct, so do not fix it", and the reason to say so out
# loud is that the two readings genuinely disagree in this estate:
#
#   * the CODE sets 10 000 ms, explicitly, on every connection it opens (this line),
#     so this is the effective value for every app query. `PRAGMA busy_timeout` is a
#     PER-CONNECTION setting — it is not a property of the database file — which is
#     why the same store can report 20 000 to an auditor that opens its own
#     connection while the app runs at 10 000.
#   * the AUTHORITY reports `PRAGMA busy_timeout = 20000` on the connections an audit
#     opens (measured 2026-09-28), which is a different number for the same database.
#
# So neither number is wrong and the difference is not a bug in either place; the
# trap is reading one as the other. "What does the code do" is answered here, and
# `scripts/co/w7_measure.py` prints the policy value plus the fresh-connection value
# side by side so the two cannot be confused again.
#
# Raising it is a one-line, restart-only change if the owner wants them equal:
#     PS_SQLITE_BUSY_TIMEOUT_MS=20000
# It is NOT made here: it would double the worst-case blocking of every writer on a
# live store, and no measurement in the W7 evidence shows that 10 s is where locks
# are lost — the retry helpers below and the unrecorded give-ups were.
SQLITE_BUSY_TIMEOUT_MS = max(
    1_000, int(os.environ.get("PS_SQLITE_BUSY_TIMEOUT_MS", "10000"))
)
SQLITE_CONNECT_TIMEOUT_S = SQLITE_BUSY_TIMEOUT_MS / 1000.0

# The retry helpers below ride out a lock the busy handler already waited for. Each
# retry attempt is itself a statement that will wait up to SQLITE_BUSY_TIMEOUT_MS,
# so `attempts x busy_timeout` is the real worst case: 8 attempts against 10 000 ms
# is 80 s of a stuck caller with nothing bounding it, and `commit_retry` was called
# from request handlers. This budget bounds the whole retry sequence for real
# (asserted in tests/test_co_w7_acceptance.py), so a caller cannot be parked for
# longer than the budget plus one final bounded attempt.
LOCK_RETRY_TOTAL_BUDGET_S = max(
    5.0, float(os.environ.get("PS_SQLITE_LOCK_RETRY_BUDGET_S", "60"))
)

# ── Per-connection memory ceilings (2026-09-16) ──────────────────────────────
# Both of these were unbounded in practice and the kernel OOM killer collected the
# process for it — six times on 2026-09-15 alone, every time at ~20 GB RSS, and
# twice inside 15 minutes.  Evidence (see journal P160 and
# ``~/phone/api-oom-report-2026-09-15.md``):
#   * ``cache_size=-64000`` is 64 MB *per connection*, and there is one connection
#     per live thread (60 DB file descriptors were open when sampled): ~3.8 GB of
#     page cache that exists whether or not it is used.
#   * ``temp_store=MEMORY`` lets a single ORDER BY / GROUP BY / DISTINCT spill the
#     whole intermediate result set into one anonymous mapping.  Sampled directly on
#     2026-09-15 23:18:45-23:19:06: RSS went 3.5 GB -> 12.5 GB in ~20 s, with one
#     anonymous mapping of 7.4 GB — a burst, not a gradual leak.  That is the shape
#     of an in-memory temp b-tree on a 1.36M-page database.
# FILE sends those sorts to /tmp instead, and 8 MB still holds the working set of
# this app's indexed lookups.  Both are env-overridable so a rollback is a restart
# with a variable set, not a code change.
SQLITE_CACHE_KB = max(512, int(os.environ.get("PS_SQLITE_CACHE_KB", "8000")))
_SQLITE_TEMP_STORE = os.environ.get("PS_SQLITE_TEMP_STORE", "FILE").strip().upper()
SQLITE_TEMP_STORE = (
    _SQLITE_TEMP_STORE
    if _SQLITE_TEMP_STORE in ("FILE", "MEMORY", "DEFAULT", "1", "2", "0")
    else "FILE"
)

# ── Bounded connection cache ─────────────────────────────────────────────────
# The per-thread cache exists to avoid paying connection setup on every call.
# Connection setup is not free here: ``sqlite3.connect`` plus the eight PRAGMAs
# (notably ``journal_mode=WAL``, which takes the file lock) run on every miss, and
# several callers call ``_get_conn`` inside hot loops. It must nevertheless be
# bounded: threads are created and destroyed constantly (anyio's request pool, the
# six ps_mcp_server processes, cron jobs), and each dead thread used to strand its
# connection and its file descriptor forever. Measured 2026-09-15 on `secratary`:
# the API's handles on secretary.db went 48 -> 88 in four minutes with 46 threads,
# and one ps_mcp_server PID held 151.
#
# WHAT MAY BE EVICTED, AND WHY IT IS ONLY THIS. A first attempt at this fix bounded
# the cache with an LRU count cap and closed the least-recently-used connection when
# it overflowed. That is not safe here and it crashed the process: ``_get_conn``
# returns a bare ``sqlite3.Connection`` that callers keep using after the call
# returns, so there is no moment at which the cache knows a connection is idle -- a
# connection whose last use was milliseconds ago may be mid-``execute`` in a live
# thread. Measured 2026-09-15 running ``tests/test_db_connection_hygiene.py`` with a
# cap of 4 and 40 concurrent threads: ``Windows fatal exception: access violation``
# with seven live threads inside ``_get_conn``. So the cache now evicts only entries
# that no thread can still be using:
#   * the owning thread object is gone (it can never touch the connection again), or
#   * the connection has not been touched for :data:`CONN_CACHE_IDLE_TTL_S` seconds.
# Entries for live, busy threads are never closed. The result is still bounded: the
# cache cannot exceed (live threads) + (recently dead threads), and the dead are
# swept, so it tracks live concurrency instead of growing with every thread the
# process has ever created -- which is what produced the measured 48 -> 88 handles.
CONN_CACHE_IDLE_TTL_S = max(
    1.0, float(os.environ.get("PS_SQLITE_CONN_CACHE_IDLE_TTL_S", "300"))
)
# A write transaction that stays open this long is LEAKED, not in flight. Python
# ``sqlite3`` leaves a transaction open when a caller errors between BEGIN and
# commit, and SQLite has exactly ONE writer: a single leaked transaction wedges
# every other writer on the box with "database is locked". Measured 2026-09-30 on
# secratary: one leaked BEGIN held the WAL write lock for 2.5 h with all threads
# idle, the DSH ingest 500ed, and the fail-closed shipper stopped sending. 15 min
# is far longer than any legitimate write here (the ingest budget is 95 s) and
# half the 30-min shipper cadence, so a real in-flight write is never touched.
LEAKED_TXN_TTL_S = max(
    60.0, float(os.environ.get("PS_SQLITE_LEAKED_TXN_TTL_S", "900"))
)
# Transient SQLite lock errors under concurrent writer load (autopilot ticks +
# HTTP handlers sharing the same DB). WAL + busy_timeout already handle the
# common case; this is a final safety net so a short-lived write-contention
# burst doesn't kill a whole agent tick or telemetry write.
_LOCKED_ERROR_MSGS = (
    "database is locked",
    "database table is locked",
    "sqlite_busy",
)


def is_locked_error(exc: BaseException) -> bool:
    """Return True if exc (possibly nested) is a transient SQLite lock error."""
    if isinstance(exc, sqlite3.OperationalError):
        msg = str(exc).lower()
        return any(token in msg for token in _LOCKED_ERROR_MSGS)
    return False


# ===========================================================================
# THE CONNECTION POLICY — enforced here, in one place (2026-09-28, W7)
# ===========================================================================
# WHY THIS SECTION EXISTS. Measured on the authority, same seven days, same box:
#
#   error_log.error_message = 'database is locked'          36 rows
#   journalctl -u secretary-api, 'database is locked'     1,846 events
#   error_log.error_message LIKE '%closed database%'          25 rows
#
# A 51x undercount, and the reason is structural rather than accidental: error_log
# receives only *unhandled* exceptions. A lock that is caught and swallowed, or a
# timeout the /health probe handles itself, leaves no row — so "a row count from
# this table is a floor, never a population count".
#
# Both failure modes come out of the way this module hands connections out, so the
# policy is made explicit and single-sourced here, and every factory below routes
# through it:
#
#   * ONE pragma set           -> _configure_connection()   (WAL, foreign_keys,
#                                 busy_timeout, synchronous, cache_size,
#                                 temp_store, wal_autocheckpoint,
#                                 journal_size_limit)
#   * ONE opener               -> connect_db() / get_db_connection()
#                                 (get_db_connection() is a FRESH caller-owned
#                                  connection; _get_conn() is the cached per-thread
#                                  one — they are not interchangeable)
#   * ONE thread-safety answer -> check_same_thread=False, because the per-thread
#                                 cache and the anyio request pool both hand a
#                                 connection to whatever thread is running; the
#                                 per-thread key is what makes that safe.
#   * ONE retry/backoff answer -> LOCK_RETRY_TOTAL_BUDGET_S + commit_retry() /
#                                 _retry_db_op(); a give-up is RECORDED, not
#                                 swallowed.
#   * closed connections are a NAMED, RECORDED error -> ClosedDatabaseUseError,
#                                 which carries the reason the connection was
#                                 closed (dead-thread sweep / idle TTL / explicit
#                                 close). Before this, the three reasons were
#                                 indistinguishable and none was counted.
CONTENTION_ERROR_TYPE = "db_contention"
_CONTENTION_RESOLUTION = (
    "counted by app.database contention recorder (informational; no action required)"
)
_DEFAULT_DB_URL: str | None = None


class ClosedDatabaseUseError(sqlite3.ProgrammingError):
    """A connection this module handed out was used after it had been closed.

    Subclasses :class:`sqlite3.ProgrammingError` deliberately, and that choice is
    the reason this is safe to ship: every existing ``except sqlite3.Error`` /
    ``except sqlite3.ProgrammingError`` / ``pytest.raises(sqlite3.ProgrammingError)``
    in this repository keeps catching it unchanged. Naming it adds no new failure
    mode — it makes the existing one traceable to the code that closed the
    connection, and countable instead of invisible.

    ``db_url``, ``closed_reason`` and ``op`` are set on the instance so a handler
    (or a log line) can say *which* database, *what* closed it, and *what* was
    attempted.
    """

    db_url: str | None = None
    closed_reason: str | None = None
    op: str | None = None


# ── Contention that survives the policy must be VISIBLE ──────────────────────
# One row per locked-and-given-up / closed-connection-use event, written into the
# existing error_log table (error_type = 'db_contention'), so the next audit counts
# rows in SQL instead of grepping systemd's journal. The owner's W7 measure script
# (scripts/co/w7_measure.py) reads exactly these rows back.
#
# Rows are marked resolved=1 with a resolution string ON PURPOSE: they are a
# measurement, not a fault to be healed, and `resolved = 0` would feed them into
# the self-healing loop, which would then open tasks about the recording of lock
# contention. The COUNT is unaffected by the flag.
#
# The write is queued, not inline. Every call site here can be inside `_db_lock`
# (the closed-use guard fires in the middle of any `with _db_lock:` block) or can
# be failing on the very lock it is trying to report; a synchronous INSERT there
# would hold the module lock across a SQLite call — the measured #1 cause of API
# hangs — and would contend with the lock that produced the event. One daemon
# thread drains a bounded queue with its own connection and a short busy timeout.
_CONTENTION_QUEUE_MAX = 1000
# An event that can never be written (the target has no error_log table, or the file
# is gone) must not wedge the queue: one poison event at the head would make every
# later event undeliverable and make flush_contention_log() never return. Terminal
# failures are counted and dropped on the first attempt; anything else is retried
# this many times before being counted and dropped.
_CONTENTION_MAX_ATTEMPTS = 3
_CONTENTION_TERMINAL_ERRORS = (
    "no such table",
    "unable to open database file",
    "no such file or directory",
    "readonly database",
    "attempt to write a readonly database",
)
_contention_queue: "deque[tuple[str, str, str, str, int]]" = deque()
_contention_lock = threading.Lock()
_contention_wake = threading.Event()
_contention_flusher: threading.Thread | None = None
_contention_counts: dict[str, int] = {
    "queued": 0,
    "written": 0,
    "dropped": 0,          # queue overflow: events lost, so an undercount is never silent
    "write_failed": 0,     # recorder could not write (locked / missing table / file gone)
    "closed_in_use": 0,    # a closed connection was USED — work was lost here
    "closed_on_handout": 0,  # a closed cached connection was detected on handout and recovered
    "closed_while_owner_alive": 0,  # the cache closed a connection a LIVE thread still held
    "locked_giveup": 0,    # retry budget exhausted on 'database is locked'
    "leaked_transaction": 0,  # a leaked write transaction was rolled back to free the lock
}
_RECORDER_CONN: "sqlite3.Connection | None" = None
_RECORDER_URL: str | None = None
_contention_inflight = 0


def contention_stats() -> dict[str, int]:
    """Process-local counters for the contention recorder.

    The AUTHORITATIVE count is the error_log rows; this is the process's own view
    of it, and it is the only place that can report what could NOT be written
    (``dropped`` / ``write_failed``). A monitor that reads the table alone can be
    undercounting; one that reads both cannot be.
    """
    with _contention_lock:
        return dict(_contention_counts)


def _remember_db_url(db_url: str) -> None:
    """Remember the last database this module opened, so a give-up can be attributed
    even when the failing call site only passes us a connection object."""
    global _DEFAULT_DB_URL
    if db_url:
        _DEFAULT_DB_URL = db_url


def _conn_db_url(conn: Any) -> str | None:
    return getattr(conn, "_ps_db_url", None) or _DEFAULT_DB_URL


def _record_contention(
    kind: str,
    message: str,
    site: str,
    db_url: str | None = None,
) -> None:
    """Queue one countable contention event. Never blocks, never raises.

    See the block comment above: this must be callable from inside ``_db_lock`` and
    from a path that is already failing on a locked database, so it only ever
    appends to a bounded deque and wakes the flusher thread.
    """
    global _contention_flusher
    target = db_url or _DEFAULT_DB_URL
    with _contention_lock:
        _contention_counts["queued"] += 1
        _contention_counts[kind] = _contention_counts.get(kind, 0) + 1
        if not target:
            _contention_counts["write_failed"] += 1
        else:
            if len(_contention_queue) >= _CONTENTION_QUEUE_MAX:
                _contention_queue.popleft()
                _contention_counts["dropped"] += 1
            _contention_queue.append((target, kind, message, site, 0))
        needs_flusher = _contention_flusher is None
    if needs_flusher:
        _start_contention_flusher()
    _contention_wake.set()


def _start_contention_flusher() -> None:
    global _contention_flusher
    with _contention_lock:
        if _contention_flusher is not None:
            return
        thread = threading.Thread(
            target=_contention_flush_loop,
            name="ps-db-contention-recorder",
            daemon=True,
        )
        _contention_flusher = thread
    thread.start()


def _contention_recorder_conn(db_url: str) -> "sqlite3.Connection | None":
    """The flusher's own connection. Created once, reused, never cached in
    ``_connections`` (so the prune can never close it) and never closed by anything
    but the flusher."""
    global _RECORDER_CONN, _RECORDER_URL
    if _RECORDER_CONN is not None and _RECORDER_URL == db_url:
        return _RECORDER_CONN
    if _RECORDER_CONN is not None:
        try:
            _RECORDER_CONN.close()
        except Exception:
            pass
        _RECORDER_CONN = None
        _RECORDER_URL = None
    try:
        conn = connect_db(db_url, busy_timeout_ms=750)
    except Exception as exc:  # pragma: no cover - depends on the database state
        _log.debug("contention recorder could not open %s: %s", db_url, exc)
        return None
    _RECORDER_CONN = conn
    _RECORDER_URL = db_url
    return conn


def _write_contention_batch(
    batch: "list[tuple[str, str, str, str, int]]",
) -> "tuple[int, list[tuple[str, str, str, str, int]]]":
    """Write one batch.

    Returns ``(written, retryable)`` where ``retryable`` holds the items that failed
    for a reason that might clear (the database was busy). Anything that failed for a
    reason that cannot clear — no ``error_log`` table, file gone, read-only — is
    counted in ``write_failed`` and dropped here, because one undeliverable event must
    not be able to wedge the queue behind it.
    """
    global _RECORDER_CONN, _RECORDER_URL
    grouped: "dict[str, list[tuple[str, str, str, str, int]]]" = {}
    for db_url, _kind, message, site, attempts in batch:
        grouped.setdefault(db_url, []).append((_kind, message, site, attempts))

    written = 0
    retryable: "list[tuple[str, str, str, str, int]]" = []
    for db_url, rows in grouped.items():
        conn = _contention_recorder_conn(db_url)
        if conn is None:
            retryable.extend(
                (db_url, kind, message, site, attempts + 1)
                for (kind, message, site, attempts) in rows
            )
            continue
        now = _now_iso()
        try:
            conn.executemany(
                """INSERT INTO error_log
                   (error_type, error_message, traceback_text, endpoint,
                    request_data, agent_id, resolved, resolution,
                    created_at, updated_at)
                   VALUES (?, ?, NULL, ?, NULL, 'db-policy', 1, ?, ?, ?)""",
                [
                    (
                        CONTENTION_ERROR_TYPE,
                        # The kind and site are embedded in the message because
                        # error_log has no column for either, and the owner's audit
                        # needs to separate "gave up on a lock" from "used a closed
                        # connection" by SQL rather than by reading prose.
                        f"{message} [db_contention kind={_kind} site={site}]",
                        site,
                        _CONTENTION_RESOLUTION,
                        now,
                        now,
                    )
                    for (_kind, message, site, _attempts) in rows
                ],
            )
            conn.commit()
            written += len(rows)
        except Exception as exc:
            message_lower = str(exc).lower()
            terminal = any(t in message_lower for t in _CONTENTION_TERMINAL_ERRORS)
            _log.debug("contention recorder write failed (%s): %s", db_url, exc)
            try:
                _RECORDER_CONN = None
                _RECORDER_URL = None
                conn.close()
            except Exception:
                pass
            for (_kind, _message, _site, attempts) in rows:
                if terminal or attempts + 1 >= _CONTENTION_MAX_ATTEMPTS:
                    with _contention_lock:
                        _contention_counts["write_failed"] += 1
                    continue
                retryable.append((db_url, _kind, _message, _site, attempts + 1))
    return written, retryable


def _contention_flush_loop() -> None:  # pragma: no cover - background thread
    global _contention_inflight
    backoff = 1.0
    while True:
        try:
            _contention_wake.wait(timeout=5.0)
            _contention_wake.clear()
            with _contention_lock:
                if not _contention_queue:
                    continue
                batch = list(_contention_queue)
                _contention_queue.clear()
                _contention_inflight += len(batch)
            written, retryable = _write_contention_batch(batch)
            with _contention_lock:
                _contention_inflight -= len(batch)
                _contention_counts["written"] += written
            if retryable:
                # Keep the events rather than dropping them; the queue bound means a
                # persistent failure shows up as `dropped`, which is counted.
                with _contention_lock:
                    for item in reversed(retryable):
                        if len(_contention_queue) >= _CONTENTION_QUEUE_MAX:
                            _contention_counts["dropped"] += 1
                            continue
                        _contention_queue.appendleft(item)
                time.sleep(backoff)
                backoff = min(backoff * 2, 30.0)
                _contention_wake.set()
            else:
                backoff = 1.0
        except Exception:  # pragma: no cover - the recorder must never die
            _log.debug("contention recorder loop error", exc_info=True)
            time.sleep(1.0)


def flush_contention_log(timeout_s: float = 5.0) -> bool:
    """Block until the recorder has nothing queued and nothing in flight.

    Returns True when everything drained. Never raises. Test and operator helper —
    production code never needs to call it, because the daemon thread drains on its
    own within 5 s. Note the two conditions: the queue empties *before* the write
    happens, so waiting on the queue alone would race the INSERT.
    """
    _contention_wake.set()
    deadline = time.monotonic() + max(0.0, timeout_s)
    while time.monotonic() < deadline:
        with _contention_lock:
            if not _contention_queue and not _contention_inflight:
                return True
        time.sleep(0.02)
    with _contention_lock:
        return not _contention_queue and not _contention_inflight


class _PolicyConnection(sqlite3.Connection):
    """The connection type this module hands out (``sqlite3.connect(factory=...)``).

    It adds exactly one behaviour on top of the stdlib connection: using a
    connection after it was closed raises :class:`ClosedDatabaseUseError`, naming
    the reason it was closed, instead of the anonymous
    ``sqlite3.ProgrammingError: Cannot operate on a closed database.``

    The reason is the whole point. This module can close a connection for three
    distinct causes and until now nothing recorded which one happened:

      * ``dead_thread_sweep``        — the owning thread exited. Safe by construction.
      * ``idle_ttl_live_owner``      — the connection was idle past
                                       :data:`CONN_CACHE_IDLE_TTL_S` and its owner
                                       thread is STILL ALIVE and may still hold the
                                       reference. This is the one that loses work.
      * ``explicit_close_*``         — ``close_db_connections()`` was called.

    ``sqlite3.Row`` row factories, ``sqlite_vec.load()`` and every existing
    ``isinstance(conn, sqlite3.Connection)`` check are unaffected: this is a
    subclass, not a wrapper.
    """

    _ps_closed = False
    _ps_closed_reason: str | None = None
    _ps_db_url: str | None = None
    _ps_key: str | None = None

    def _ps_mark_closed(self, reason: str) -> None:
        self._ps_closed = True
        if self._ps_closed_reason is None:
            self._ps_closed_reason = reason

    def _ps_is_closed(self) -> bool:
        return bool(self._ps_closed)

    def _ps_raise_if_closed(self, op: str) -> None:
        if not self._ps_closed:
            return
        reason = self._ps_closed_reason or "unknown"
        err = ClosedDatabaseUseError(
            "Cannot operate on a closed database: "
            f"{op}() on {self._ps_db_url or '<unknown db>'} — closed by {reason}"
        )
        err.db_url = self._ps_db_url
        err.closed_reason = reason
        err.op = op
        _record_contention(
            "closed_in_use",
            f"Cannot operate on a closed database ({reason}) at {op}()",
            f"app/database.py:{op}",
            db_url=self._ps_db_url,
        )
        raise err

    def close(self) -> None:
        if self._ps_closed:
            return
        self._ps_closed = True
        if self._ps_closed_reason is None:
            self._ps_closed_reason = "explicit_close_by_owner"
        super().close()

    # ``execute``/``cursor`` are the two paths that actually produce the measured
    # message; ``executemany``/``executescript``/``commit``/``rollback`` are covered
    # for the same reason. The check is one attribute load on the hot path.
    def _ps_rollback_on_lock(self, exc: BaseException) -> None:
        """Roll back the implicit transaction a lock-failed statement left open.

        Python's default ``isolation_level=""`` opens a transaction on the first
        DML. When that DML fails with ``database is locked`` the transaction stays
        OPEN on the connection, so a later uncommitted write on this cached
        connection holds the single SQLite write lock until something reaps it
        (measured in production at 900-2179 s). Rolling back here closes that
        window at every call site, because every app connection is built with
        ``factory=_PolicyConnection``. It never masks the original error: the
        caller still sees the ``OperationalError`` it would have seen before.
        """
        if not is_locked_error(exc) or not self.in_transaction:
            return
        try:
            super().rollback()
        except Exception:
            pass

    def execute(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._ps_raise_if_closed("execute")
        try:
            return super().execute(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            self._ps_rollback_on_lock(exc)
            raise

    def executemany(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._ps_raise_if_closed("executemany")
        try:
            return super().executemany(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            self._ps_rollback_on_lock(exc)
            raise

    def executescript(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._ps_raise_if_closed("executescript")
        try:
            return super().executescript(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            self._ps_rollback_on_lock(exc)
            raise

    def cursor(self, *args: Any, **kwargs: Any):  # type: ignore[override]
        self._ps_raise_if_closed("cursor")
        return super().cursor(*args, **kwargs)

    def commit(self) -> None:  # type: ignore[override]
        self._ps_raise_if_closed("commit")
        return super().commit()

    def rollback(self) -> None:  # type: ignore[override]
        self._ps_raise_if_closed("rollback")
        return super().rollback()


def connection_policy() -> dict[str, Any]:
    """The policy this module applies to every connection it opens, as data.

    Reported by ``scripts/co/w7_measure.py`` and asserted by
    ``tests/test_co_w7_acceptance.py`` so the policy cannot drift out of one place
    without a test noticing.
    """
    return {
        "busy_timeout_ms": SQLITE_BUSY_TIMEOUT_MS,
        "connect_timeout_s": SQLITE_CONNECT_TIMEOUT_S,
        "journal_mode": "wal",
        "foreign_keys": True,
        "synchronous": "NORMAL",
        "cache_size_kb": SQLITE_CACHE_KB,
        "temp_store": SQLITE_TEMP_STORE,
        "wal_autocheckpoint_pages": 10000,
        "journal_size_limit_bytes": 67108864,
        "check_same_thread": False,
        "lock_retry_total_budget_s": LOCK_RETRY_TOTAL_BUDGET_S,
        "conn_cache_idle_ttl_s": CONN_CACHE_IDLE_TTL_S,
    }


def _db_file_path(db_url: str) -> str:
    """Turn a ``sqlite:///...`` URL into a filesystem path (``connection_key`` and
    ``close_db_connections`` match on the URL form, so both spellings must work)."""
    path = db_url
    if path.startswith("sqlite:///"):
        path = path[len("sqlite:///") :]
    elif path.startswith("sqlite://"):
        path = path[len("sqlite://") :]
    return path


def _configure_connection(
    conn: sqlite3.Connection, *, busy_timeout_ms: int | None = None
) -> sqlite3.Connection:
    """THE one place connection pragmas are set. Nothing else in this module runs a
    PRAGMA at connect time.

    ``busy_timeout`` is set FIRST, deliberately (the same ordering the family_chat
    store uses and documents): it is what makes every later statement — including
    ``journal_mode=WAL``, which needs the file lock when the database is not already
    in WAL — wait rather than fail instantly. A locked error on a pragma is retried
    inside this function's own bounded budget so that ``_get_conn`` can never raise
    "database is locked" out of connection setup.
    """
    ms = SQLITE_BUSY_TIMEOUT_MS if busy_timeout_ms is None else max(0, int(busy_timeout_ms))
    conn.row_factory = sqlite3.Row
    statements = (
        f"PRAGMA busy_timeout={ms}",
        "PRAGMA journal_mode=WAL",
        "PRAGMA foreign_keys=ON",
        "PRAGMA synchronous=NORMAL",  # safe with WAL, 2x faster writes
        # 8MB page cache per connection (not 64MB: it multiplies by live threads).
        f"PRAGMA cache_size=-{SQLITE_CACHE_KB}",
        # FILE, not MEMORY: an in-memory temp store makes a large sort an unbounded
        # RAM allocation, and that is what OOM-killed this process on 2026-09-15.
        f"PRAGMA temp_store={SQLITE_TEMP_STORE}",
        # F2 (2026-08-30): cap the WAL so it can't balloon (was 456MB).
        "PRAGMA wal_autocheckpoint=10000",  # checkpoint every ~40MB
        "PRAGMA journal_size_limit=67108864",  # truncate WAL to <=64MB
    )
    deadline = time.monotonic() + max(1.0, ms / 1000.0)
    for sql in statements:
        delay = 0.05
        while True:
            try:
                conn.execute(sql)
                break
            except sqlite3.OperationalError as exc:
                if not is_locked_error(exc) or time.monotonic() >= deadline:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 0.5)
    return conn


def _open_readonly_probe_connection(path: str, budget_s: float) -> sqlite3.Connection:
    """Open the probe connection: ``mode=ro``, so it can never write the database."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=budget_s)
    conn.execute(f"PRAGMA busy_timeout={int(budget_s * 1000)}")
    return conn


def probe_database_readonly(db_url: str, *, busy_timeout_s: float | None = None) -> float:
    """``SELECT 1`` on a FRESH READ-ONLY connection; returns elapsed milliseconds.

    WHY THIS IS NOT :func:`_get_conn` (c10-lockfix, 2026-10-15). ``_get_conn`` takes
    the process-global ``_db_lock``, so a probe through it can be blocked by the very
    lock it exists to inspect -- and a probe blocked inside anyio's threadpool cannot
    be cancelled by the ``asyncio.wait_for`` that is supposed to bound it
    (``run_in_threadpool`` runs with ``abandon_on_cancel=False``). That is how one
    long ingest made ``/health`` hang while the process still reported ``active``.

    This opens its own connection with ``mode=ro`` (it cannot write), waits no longer
    than ``busy_timeout_s`` for SQLite itself, and closes it. It holds no lock any
    other part of the app needs.

    Measured on this box, 2026-10-15T00:2xZ against the live 28 GiB authority
    database: connect 0.02-0.11 ms, ``SELECT 1`` 0.00-0.02 ms. The 2026-09-28
    measurement of the same shape was p50 0.2 ms / p95 0.7 ms / max 1.0 ms while the
    shared-lock path was timing out at 2 s.
    """
    path = _db_file_path(db_url)
    if not path:
        raise ValueError(f"probe_database_readonly needs a sqlite URL, got {db_url!r}")
    budget = (
        HEALTH_PROBE_BUSY_TIMEOUT_S
        if busy_timeout_s is None
        else max(0.05, float(busy_timeout_s))
    )
    started = time.monotonic()
    conn = _open_readonly_probe_connection(path, budget)
    try:
        conn.execute("SELECT 1").fetchone()
    finally:
        conn.close()
    return (time.monotonic() - started) * 1000.0


def connect_db(
    db_url: str,
    *,
    busy_timeout_ms: int | None = None,
    check_same_thread: bool = False,
    uri: bool = False,
    mkdir: bool = True,
) -> sqlite3.Connection:
    """Open ONE policy-configured SQLite connection. **The caller owns it and closes it.**

    This and :func:`get_db_connection` are the only sanctioned ways to open a
    connection in this module, and every one of them applies
    :func:`_configure_connection` — so no call site can obtain an unconfigured
    connection by accident.

    Not to be confused with :func:`_get_conn`, which returns the *cached per-thread*
    connection that callers must NOT close. Confusing the two is how
    ``Cannot operate on a closed database.`` gets manufactured: a caller that closes
    a connection it borrowed from the cache has just closed it for every later call
    on that thread.
    """
    timeout_s = (
        SQLITE_CONNECT_TIMEOUT_S
        if busy_timeout_ms is None
        else max(0, int(busy_timeout_ms)) / 1000.0
    )
    target = db_url if uri else _db_file_path(db_url)
    if not uri and mkdir:
        try:
            Path(target).parent.mkdir(parents=True, exist_ok=True)
        except OSError:  # pragma: no cover - mkdir is best-effort for odd paths
            pass
    conn = sqlite3.connect(
        target,
        check_same_thread=check_same_thread,
        timeout=timeout_s,
        uri=uri,
        factory=_PolicyConnection,
    )
    conn._ps_db_url = db_url
    try:
        _configure_connection(conn, busy_timeout_ms=busy_timeout_ms)
    except Exception:
        try:
            conn.close()
        except Exception:
            pass
        raise
    _remember_db_url(db_url)
    return conn


def get_db_connection(db_url: str, **kwargs: Any) -> sqlite3.Connection:
    """A FRESH, policy-configured connection that the caller owns and must close.

    This name is why it exists. Four call sites in this repository do
    ``from app.database import get_db_connection`` inside a
    ``try: ... except Exception: pass`` block:

        app/sms_service.py:835        — DB-backed duplicate-SMS suppression (30 min)
        app/sms_service.py:1042       — per-number outbound quota
        app/chat_action_runtime.py:1914 — owner-SMS daily cap (max 2/day)
        app/chat_action_owner.py:487  — owner-SMS daily cap (max 2/day)

    The name did not exist in this module, so all four raised ImportError on every
    single call and the ``except Exception: pass`` swallowed it. The DB-backed
    duplicate-SMS suppression and the owner-SMS daily cap have therefore never once
    executed. Defining it here fixes all four without touching a file outside this
    one, and gives them the same policy as everything else.

    Returns a NEW connection, not the thread-local cached one, because every one of
    those call sites closes it in a ``finally``.
    """
    return connect_db(db_url, **kwargs)


def get_conn(db_url: str) -> sqlite3.Connection:
    """The CACHED per-thread connection. **Do not close it.**

    The second half of the same defect as :func:`get_db_connection`, and the opposite
    semantics, which is why both are documented together:

        app/main.py:6766  ``from app.database import get_conn`` in
        ``fleet_location_history`` — the handler uses ``row["id"]`` (so it needs the
        ``sqlite3.Row`` factory) and never closes the connection. The audit at
        ``docs/audits/company-next-level/04-reliability.md`` records the resulting
        ``cannot import name 'get_conn'`` six times, every one of which returned a 500
        before touching the database.

    This is an alias of :func:`_get_conn` and NOT of :func:`get_db_connection`, and
    that is the whole point of naming it here: the caller does not close it, so
    handing it a fresh connection would leak one handle per request, and returning the
    cached one from ``get_db_connection`` would close a connection the thread is
    still using.

    Prefer ``_get_conn`` in new code, or ``connect_db`` when you want a connection you
    own. This exists so the four existing call sites stop raising ImportError.
    """
    return _get_conn(db_url)


def commit_retry(
    conn,
    attempts: int = 8,
    base_delay: float = 0.05,
    commit_fn=None,
    total_budget_s: float | None = None,
    db_url: str | None = None,
    site: str = "commit_retry",
) -> None:
    """conn.commit() that retries transient 'database is locked' with backoff.

    The busy_timeout pragma already makes SQLite wait for the writer lock; this
    is the safety net for the rare case where a competing write transaction is
    held so long the busy wait itself expires. Retries briefly, then re-raises.

    ``commit_fn`` defaults to ``conn.commit`` and is injectable for testing.

    ``total_budget_s`` bounds the WHOLE sequence, and that bound is the point: each
    attempt is itself a statement that waits up to ``SQLITE_BUSY_TIMEOUT_MS``, so
    ``attempts x busy_timeout`` — 8 x 20 s = 160 s — was the real, undocumented worst
    case before this parameter existed. Exhausting the budget is not a silent event:
    the give-up is recorded as a countable ``error_log`` row (see
    :func:`_record_contention`) so the next audit does not have to read systemd's
    journal to find it.
    """
    if commit_fn is None:
        commit_fn = conn.commit
    if total_budget_s is None:
        total_budget_s = LOCK_RETRY_TOTAL_BUDGET_S
    started = time.monotonic()
    delay = base_delay
    for _ in range(attempts):
        try:
            commit_fn()
            return
        except sqlite3.OperationalError as exc:
            if not is_locked_error(exc):
                raise
            if time.monotonic() - started + delay > total_budget_s:
                break
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    try:
        commit_fn()
    except sqlite3.OperationalError as exc:
        if is_locked_error(exc):
            _record_contention(
                "locked_giveup",
                f"database is locked (gave up at {site} after {attempts} attempts "
                f"within a {total_budget_s:.0f}s budget): {exc}",
                site,
                db_url=db_url or _conn_db_url(conn),
            )
        raise


_SQLITE_VEC_AVAILABLE: bool | None = None
_SQLITE_VEC_DISABLED_REASON: str | None = None
TASK_COMPLETED_STATUSES = ("done", "completed", "closed")
TASK_ACTIVE_STATUSES = ("open", "in_progress", "pending", "blocked")

# The statuses in which a task still has work pending, which is a DIFFERENT question from
# "is this task consuming ceiling capacity" (that is TASK_ACTIVE_STATUSES). Duplicate
# detection asks the first question, and answering it with the second set is how three
# duplicates of task #25106 were created: a `blocked` task was invisible, so blocking it
# licensed copies of it. The extra values below are not invented -- each one appears in the
# live table (measured 2026-09-15: 'waiting on customer' 3, 'in-progress' 3,
# 'awaiting_part' 1, 'paused' 1, 'todo' 1).
TASK_PENDING_WORK_STATUSES = TASK_ACTIVE_STATUSES + (
    "in-progress",
    "todo",
    "waiting_on_customer",
    "waiting on customer",
    "awaiting_part",
    "paused",
)

_LEGACY_ASSIGNMENT_AGENT_ALIASES: dict[str, str] = {
    "dept_operations": "dept_business_ops",
    "dept_ops": "dept_business_ops",
    "dept_sales": "dept_business_ops",
    "dept_communications": "dept_business_ops",
    "dept_it": "dept_engineering",
    "home_life": "dept_home_life",
    "personal-secretary": "dept_engineering",
    "personal_secretary": "dept_engineering",
    # 2026-08-31: standing_work_orders use semantic department names in the
    # `department` column, which work_orders.py assigns raw to goals/steps.
    # `finance` and `executive` are NOT agent IDs — nobody can claim goals
    # assigned to them, so the goal sits active until the lifecycle sweep
    # kills it as stale. This caused the 171/175 daily-finance-sync failures
    # (steps never claimed) and the ceo-vp-sync (dept=executive) failures.
    "finance": "dept_finance",
    "executive": "orchestrator",
    # 2026-08-31: ghost-agent sweep found more semantic/legacy names
    # assigned to active goal_steps/goal_plans. Map them to live agents.
    "dept_communication": "dept_comms_relationships",
    "dept_comms": "dept_comms_relationships",
    "dept_comms_relationships_reviewer": "comms_relationships_reviewer",
    "dept_model_ops": "dept_ai_platform",
    "dept_office": "dept_business_ops",
    # 2026-08-31: legacy `dept_evolution` ghost — one active plan
    # (390a962731e3) + step 38566 were orphaned to it; canonical is
    # dept_evolution_reliability (which ticks).
    "dept_evolution": "dept_evolution_reliability",
    # 2026-09-14: four names the ghost-agent monitor kept reporting. Sibling
    # `home_life -> dept_home_life` above already set the pattern, and the
    # system itself reassigned `dept_home_and_life -> dept_home_life` on
    # 2026-09-11 (activity_log 303889), so these are not new guesses.
    #
    # dept_executive_assistant is the one real judgement call. The audit's
    # evidence pointed at dept_home_life (personal medical review), but the
    # live row it would capture is the CHEMED/radiology owner-review plan, and
    # routing owner-review material into an autonomous department is worse than
    # routing it to the orchestrator, which is where owner escalation already
    # lives. The item is separately tracked as an owner question, so nothing is
    # lost by NOT auto-assigning it to a department that might act on it.
    "dept_home_and_life": "dept_home_life",
    "dept_personal": "dept_home_life",
    "dept_ceo": "orchestrator",
    "dept_executive_assistant": "orchestrator",
    # 2026-09-15: the bare `dept_executive`, which all three of its siblings above already
    # cover. Task #25083 -- the CHEMED/radiology owner-review item those comments discuss --
    # was assigned to it and sat in_progress for 5.7h, invisible to the ghost-agent monitor
    # because that scans goal_plans and goal_steps and not `tasks`. Zero occurrences in
    # company_blueprint.py, so it is a ghost, not a department.
    "dept_executive": "orchestrator",
}


def canonicalize_assignment_agent(agent_id: Any | None) -> str | None:
    if agent_id is None:
        return None
    normalized = str(agent_id).strip()
    if not normalized:
        return None
    return _LEGACY_ASSIGNMENT_AGENT_ALIASES.get(normalized, normalized)


def _normalize_assignment_alias_rows(conn: sqlite3.Connection) -> None:
    for legacy_agent_id, canonical_agent_id in _LEGACY_ASSIGNMENT_AGENT_ALIASES.items():
        try:
            conn.execute(
                "UPDATE tasks SET assigned_to = ? WHERE assigned_to = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE goal_plans SET assigned_agent = ? WHERE assigned_agent = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE goal_steps SET assigned_agent = ? WHERE assigned_agent = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE delegations SET from_agent_id = ? WHERE from_agent_id = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE delegations SET to_agent_id = ? WHERE to_agent_id = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE action_approval_queue SET agent_id = ? WHERE agent_id = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE projects SET lead_agent = ? WHERE lead_agent = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE job_queue SET agent_id = ? WHERE agent_id = ?",
                (canonical_agent_id, legacy_agent_id),
            )
            conn.execute(
                "UPDATE work_sessions SET agent_id = ? WHERE agent_id = ?",
                (canonical_agent_id, legacy_agent_id),
            )
        except sqlite3.OperationalError:
            continue


def _safe_migrate(conn: sqlite3.Connection, sql: str) -> None:
    """Run a migration SQL statement, silencing only 'duplicate column' errors.

    Real errors (disk I/O, corruption) are logged as warnings rather than
    silently swallowed so operators can diagnose schema drift.
    """
    try:
        conn.execute(sql)
        conn.commit()
    except sqlite3.OperationalError as exc:
        msg = str(exc).lower()
        if "duplicate column" in msg or "already exists" in msg:
            return  # expected on repeat startup
        _log.warning("Migration SQL failed (continuing): %s — %s", sql[:120], exc)
    except Exception as exc:
        _log.warning("Migration SQL failed (continuing): %s — %s", sql[:120], exc)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sqlite_vec_config_enabled() -> bool:
    try:
        from app.config import settings as app_settings

        return bool(getattr(app_settings, "sqlite_vec_enabled", True))
    except Exception:
        return True


def _disable_sqlite_vec(reason: str, *, log_level: str = "info") -> None:
    global _SQLITE_VEC_AVAILABLE, _SQLITE_VEC_DISABLED_REASON

    should_log = (
        _SQLITE_VEC_AVAILABLE is not False or _SQLITE_VEC_DISABLED_REASON != reason
    )
    _SQLITE_VEC_AVAILABLE = False
    _SQLITE_VEC_DISABLED_REASON = reason
    if not should_log:
        return
    if log_level == "debug":
        _log.debug("sqlite-vec unavailable: %s", reason)
        return
    if log_level == "warning":
        _log.warning("sqlite-vec unavailable: %s", reason)
        return
    _log.info("sqlite-vec disabled: %s", reason)


def _ensure_sqlite_vec_loaded(conn: sqlite3.Connection) -> bool:
    global _SQLITE_VEC_AVAILABLE, _SQLITE_VEC_DISABLED_REASON

    if not _sqlite_vec_config_enabled():
        _disable_sqlite_vec("disabled by config", log_level="debug")
        return False
    if _SQLITE_VEC_AVAILABLE is False:
        return False

    try:
        import sqlite_vec  # type: ignore[import-untyped]
    except ImportError:
        _disable_sqlite_vec("not installed", log_level="debug")
        return False

    try:
        sqlite_vec.load(conn)
    except sqlite3.OperationalError as exc:
        message = str(exc).strip() or exc.__class__.__name__
        if "not authorized" in message.lower():
            _disable_sqlite_vec(
                "extension loading is not authorized by this SQLite build",
                log_level="info",
            )
            return False
        _disable_sqlite_vec(message, log_level="warning")
        return False
    except Exception as exc:
        message = str(exc).strip() or exc.__class__.__name__
        _disable_sqlite_vec(message, log_level="warning")
        return False

    _SQLITE_VEC_AVAILABLE = True
    _SQLITE_VEC_DISABLED_REASON = None
    return True


def connection_key(db_url: str) -> str:
    """Return the cache key for the calling thread's connection to ``db_url``.

    Single source of truth for the "url:thread_id" format: ``_get_conn``,
    ``close_db_connections`` and the tests all need to agree on it, and it must not
    change shape — ``close_db_connections`` matches on the ``f"{db_url}:"`` prefix.
    """
    return f"{db_url}:{threading.get_ident()}"


def _get_conn(db_url: str) -> sqlite3.Connection:
    """Return a thread-local connection, creating the DB if needed.

    Validates the connection is still alive and reconnects if necessary.

    IMPORTANT: _db_lock only guards the _connections dict, NOT SQLite operations.
    SQLite has its own internal locking (WAL mode allows concurrent reads).
    Holding _db_lock during SQLite calls was the #1 cause of API hangs — the
    health endpoint would block waiting for a long-running autopilot query.

    IMPORTANT: the connection returned here is CACHED and MUST NOT BE CLOSED by the
    caller. Closing it closes it for every later call on this thread. A caller that
    needs a connection it owns should call :func:`connect_db` /
    :func:`get_db_connection` instead.

    Opening goes through :func:`connect_db`, so there is exactly one place in this
    module where a connection is created and exactly one place where its pragmas are
    set (:func:`_configure_connection`).
    """
    key = connection_key(db_url)
    _remember_db_url(db_url)

    # Fast path: grab the existing connection. The wait on _db_lock is BOUNDED.
    #
    # Raising a clear error must always win over parking a threadpool worker
    # forever: a parked worker is leaked, the threadpool's token budget is finite,
    # and enough leaks stop the whole app serving (see DB_LOCK_WAIT_S above). The
    # lock is NOT held on this path, so there is nothing to release before raising.
    probe_s = min(DB_LOCK_PROBE_S, DB_LOCK_WAIT_S)
    if not _db_lock.acquire(timeout=probe_s):
        remaining_s = max(0.0, DB_LOCK_WAIT_S - probe_s)
        _log.warning(
            "_get_conn: _db_lock contended for key %s; waiting up to %.1fs more "
            "(bounded: DB_LOCK_WAIT_S=%.1fs)",
            key,
            remaining_s,
            DB_LOCK_WAIT_S,
        )
        if not _db_lock.acquire(timeout=remaining_s):
            _record_contention(
                "db_lock_timeout",
                f"_db_lock not acquired within {DB_LOCK_WAIT_S:.1f}s in _get_conn "
                f"(key {key}): another thread of this process is holding the "
                f"connection-cache lock",
                "app/database.py:_get_conn",
                db_url=db_url,
            )
            raise DBLockTimeout(
                f"database is locked: in-process _db_lock wait exceeded "
                f"{DB_LOCK_WAIT_S:.1f}s for {key} (the process is busy with itself; "
                f"no SQLite lock was involved)"
            )

    conn = None
    try:
        conn = _connections.get(key)
        if conn is not None:
            _connections.move_to_end(key)
            _conn_last_used[key] = time.monotonic()
    finally:
        _db_lock.release()

    if conn is not None:
        # Probe OUTSIDE the lock. `_db_lock` guards the _connections dict and nothing
        # else (see this function's docstring): holding it across a SQLite call
        # serialised every DB access in the process behind one `SELECT 1` per call,
        # and /v1/models alone calls _get_conn 34 times per request. A concurrent
        # prune can close this connection while the probe runs; that is the
        # `closed_on_handout` recovery below, not a new race.
        alive = False
        if isinstance(conn, _PolicyConnection) and conn._ps_is_closed():
            # The cache closed this connection while this thread still held it.
            # Recovered, so this is NOT the same event as a closed_in_use: it is
            # counted separately, on purpose, because one means "work was lost"
            # and this one means "a reconnect was paid".
            _record_contention(
                "closed_on_handout",
                "Cannot operate on a closed database (detected on handout and "
                f"reconnected; closed by {conn._ps_closed_reason or 'unknown'})",
                "app/database.py:_get_conn",
                db_url=db_url,
            )
            _log.warning(
                "DB connection for %s was closed by %s; reconnecting",
                key,
                conn._ps_closed_reason or "unknown",
            )
        else:
            try:
                conn.execute("SELECT 1")
                alive = True
            except (sqlite3.Error, sqlite3.ProgrammingError) as exc:
                # Connection is dead -- remove and reconnect
                _log.warning("DB connection stale for %s, reconnecting: %s", key, exc)

        if alive:
            with _db_lock:
                _note_transaction_state_locked(key, conn, time.monotonic())
                # Reap here too, not only on the miss path below: a thread whose
                # connection stays in cache hits this branch forever, so a leaked
                # entry in the cache would otherwise never be revisited.
                _prune_connection_cache_locked(protect_key=key, defer=True)
            close_deferred_db_closes()
            return conn

        # Dead or already closed: forget it, then close outside the lock.
        with _db_lock:
            _connections.pop(key, None)
            _conn_last_used.pop(key, None)
            _conn_txn_since.pop(key, None)
        try:
            conn.close()
        except Exception:
            pass

    # Only create a new connection if we didn't return one above. The lock is
    # already released, so the expensive connect() call -- which can block for up to
    # `timeout` seconds waiting for the database file lock -- is not under it.

    # Create new connection OUTSIDE the lock — sqlite3.connect() can block
    # for up to `timeout` seconds waiting for the database file lock.
    conn = connect_db(db_url)
    conn._ps_key = key

    # Store in dict under lock and keep the cache bounded.
    _db_lock.acquire()
    try:
        _connections[key] = conn
        _connections.move_to_end(key)
        _conn_last_used[key] = time.monotonic()
        _conn_txn_since.pop(key, None)
        _prune_connection_cache_locked(protect_key=key, defer=True)
    finally:
        _db_lock.release()
    close_deferred_db_closes()
    return conn


def _note_transaction_state_locked(
    key: str, conn: sqlite3.Connection, now: float
) -> None:
    """Record when a cached connection was first seen holding a transaction.

    Caller holds ``_db_lock``. Best-effort: a connection that cannot answer
    ``in_transaction`` is simply not tracked.
    """
    try:
        if conn.in_transaction:
            _conn_txn_since.setdefault(key, now)
        else:
            _conn_txn_since.pop(key, None)
    except Exception:  # pragma: no cover - defensive
        pass


def _deferred_evict(
    key: str,
    candidates: "list[tuple[str, sqlite3.Connection]]",
    deferred: "list[tuple[str, sqlite3.Connection]] | None",
) -> None:
    """Evict ``key`` from the cache and hand it to the caller for closing.

    The entry is popped from every cache dict HERE, under ``_db_lock``, so no
    concurrent ``_get_conn`` can be handed it; the caller then does the close
    with the lock RELEASED.
    """
    conn = _connections.pop(key, None)
    _conn_last_used.pop(key, None)
    _conn_txn_since.pop(key, None)
    if conn is None:
        return
    candidates.append((key, conn))
    if deferred is not None:
        deferred.append((key, conn))


def _close_evicted(
    candidates: "list[tuple[str, sqlite3.Connection]]", reason: str
) -> int:
    """Closed evicted connections (rolling back if needed). NO lock is held."""
    closed = 0
    for key, conn in candidates:
        try:
            if conn.in_transaction:
                conn.rollback()
        except Exception:  # pragma: no cover - a connection that cannot be asked
            pass
        marker = getattr(conn, "_ps_mark_closed", None)
        if marker is not None:
            try:
                marker(reason)
            except Exception:  # pragma: no cover - defensive
                pass
        try:
            conn.close()
            closed += 1
        except Exception:
            pass
    return closed


def close_deferred_db_closes() -> int:
    """Run the prune SQLite work queued while ``_db_lock`` was held.

    MUST be called with ``_db_lock`` RELEASED. Returns the number of
    connections closed.
    """
    if not _deferred_closes and not _deferred_reaps:
        return 0
    reaps = list(_deferred_reaps)
    _deferred_reaps.clear()
    batch = list(_deferred_closes)
    _deferred_closes.clear()
    _reap_leaked_transactions(reaps)
    return _close_evicted(batch, reason="cache_prune")


def _reap_leaked_transactions(
    reaps: "list[tuple[str, sqlite3.Connection, float]]",
) -> int:
    """Roll back leaked write transactions. NO lock may be held for the rollback.

    Item 168. ``conn.rollback()`` releases the SQLite write lock and can block for
    seconds; the caller of this helper must therefore not hold ``_db_lock``. The
    transaction clock is cleared under the lock AFTER the rollback, so a reader
    never sees the clock cleared while the write lock is still held.
    """
    reaped = 0
    for key, conn, age in reaps:
        try:
            if not conn.in_transaction:
                with _db_lock:
                    _conn_txn_since.pop(key, None)
                continue
            conn.rollback()
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("leaked-transaction reap failed for %s: %s", key, exc)
            continue
        with _db_lock:
            _conn_txn_since.pop(key, None)
        _record_contention(
            "leaked_transaction",
            f"leaked write transaction open for {age:.0f}s on {key}; rolled back "
            "to release the SQLite write lock",
            "app/database.py:_reap_leaked_transactions",
        )
        _log.error(
            "Released a leaked SQLite write transaction on %s after %.0fs -- the "
            "connection never committed or rolled back and every other writer "
            "was blocked on it",
            key,
            age,
        )
        reaped += 1
    return reaped


def _prune_connection_cache_locked(
    protect_key: str | None = None,
    *,
    now: float | None = None,
    defer: bool = False,
) -> int:
    """Close cached connections that no thread can still be using.

    Caller MUST hold ``_db_lock``. Two things are evictable and nothing else:

    * the entry's owning thread object is gone (so nobody can hold a reference to
      that thread's connection and use it), or
    * the connection has not been touched for ``CONN_CACHE_IDLE_TTL_S`` seconds.

    ``protect_key`` — normally the key of the thread asking for a connection right
    now — is never closed. A connection with an open transaction is skipped rather
    than rolled back: closing it would discard another thread's in-flight write,
    which is the "work is silently re-done" failure this change exists to stop.

    Deliberately NOT a count cap. ``_get_conn`` hands out a bare connection that the
    caller keeps using after the call returns, so the cache cannot tell an idle
    connection from one that is mid-statement; closing by recency is how the first
    version of this fix produced ``access violation`` crashes with live threads
    inside ``_get_conn``. See the block comment above ``CONN_CACHE_IDLE_TTL_S``.

    Returns the number of connections closed.
    """
    if now is None:
        now = time.monotonic()

    # A caller that already holds _db_lock passes defer=True: the close is queued
    # on the module list and run by close_deferred_db_closes() AFTER the lock is
    # released. A caller holding no lock runs it inline below.
    deferred = _deferred_closes if defer else None
    candidates: "list[tuple[str, sqlite3.Connection]]" = []
    reaps: "list[tuple[str, sqlite3.Connection, float]]" = []
    closed = 0

    # Dead threads: no live code path can reach their connection, so it can be
    # closed. Membership in ``threading.enumerate()`` (not a weak reference to the
    # thread object) is the load-bearing check: a finished thread leaves ``_active``
    # as soon as ``join()`` returns, while its thread object can survive on a
    # thread/frame reference cycle until the next ``gc`` pass -- measured 2026-09-15
    # on this host, where the weakref was still alive but the ident was already gone.
    # Enumerate is 4 us with 60 threads, against ~a connect + eight PRAGMAs on the
    # miss path it runs on, so it is not worth throttling.
    try:
        live_ids = {t.ident for t in threading.enumerate()}
    except Exception:  # pragma: no cover - defensive
        live_ids = None
    if live_ids is not None:
        for key in list(_connections):
            if key == protect_key:
                continue
            owner_thread_id = _key_thread_id(key)
            if owner_thread_id is None:
                continue  # not a per-thread key; leave it alone
            if owner_thread_id in live_ids:
                continue
            _deferred_evict(key, candidates, deferred)

    # Idle TTL: a connection that has not been touched in a long while.
    #
    # FIXED 2026-09-28. This loop used to close a connection whose owning thread was
    # still ALIVE, and the owner's next use of the reference it was still holding
    # raised "Cannot operate on a closed database." Measured on the authority ten
    # hours after W7 made the event visible: `closed_while_owner_alive` fired ~15
    # times an hour, 158 times in that window, against 25 rows in all the months
    # before it was counted. It is now skipped, exactly as the dead-thread pass above
    # skips live owners.
    #
    # The case this loop was written for -- a process-lifetime thread that stops
    # using a database and would otherwise hold its handle forever -- is already
    # served by that dead-thread pass, which has its own test. Connections whose
    # owner cannot be determined are still swept, so the loop keeps doing work.
    for key in list(_connections):
        if key == protect_key or key not in _conn_last_used:
            continue
        if now - _conn_last_used[key] < CONN_CACHE_IDLE_TTL_S:
            continue
        owner_thread_id = _key_thread_id(key)
        owner_alive = bool(live_ids) and owner_thread_id in live_ids
        if owner_alive:
            # Never close a connection its owner can still reach. The reclamation
            # this loop exists for is done by the dead-thread pass above; doing it
            # here as well only produced "Cannot operate on a closed database."
            continue
        _deferred_evict(key, candidates, deferred)

    # ── Leaked-transaction pass ──────────────────────────────────────────────
    # A write transaction the owner opened and never ended is not "in flight". It
    # is a leak, and because SQLite has exactly one writer it holds the write lock
    # for the whole process -- every other writer on the box then fails with
    # "database is locked" until the process restarts. Measured 2026-09-30: one
    # leaked BEGIN 500ed the DSH session ingest for 2.5 h, so secratary's own new
    # session was never archived and check-dsh-freshness.py read "the shipper is
    # not sending". The two sweeps above correctly never roll back a LIVE write;
    # this pass bounds a leak by time instead, so it can never wedge the box.
    for key in list(_connections):
        # Deliberately NOT skipped for protect_key: this pass only rolls a leaked
        # transaction back (it never closes the connection the caller just got), and
        # the caller's OWN cached connection is the one a thread leaks and then keeps
        # handing back to itself. Skipping it would let that thread protect its own
        # leak forever.
        if key not in _conn_txn_since:
            continue
        age = now - _conn_txn_since[key]
        if age < LEAKED_TXN_TTL_S:
            continue
        conn = _connections.get(key)
        if conn is None:
            _conn_txn_since.pop(key, None)
            continue
        try:
            if not conn.in_transaction:
                _conn_txn_since.pop(key, None)
                continue
        except Exception as exc:  # pragma: no cover - defensive
            _log.warning("leaked-transaction reap failed for %s: %s", key, exc)
            continue
        # ITEM 168: collect only. conn.rollback() below would be a SQLite call that
        # can block for seconds while _db_lock -- the lock every DB access in the
        # process goes through -- is held by our caller (_get_conn passes
        # defer=True). The rollback is performed by _reap_leaked_transactions()
        # after the lock is released, or inline here when the caller holds no lock.
        reaps.append((key, conn, age))

    if reaps:
        if deferred is None:
            _reap_leaked_transactions(reaps)
        else:
            _deferred_reaps.extend(reaps)

    if deferred is None:
        closed += _close_evicted(candidates, reason="cache_prune")
    return closed


def _key_thread_id(key: str) -> int | None:
    """Extract the thread id from a cache key, or None if the key is not per-thread."""
    _, _, tail = key.rpartition(":")
    try:
        return int(tail)
    except ValueError:
        return None


def _close_cached_connection_locked(
    key: str, reason: str = "cache_prune", *, allow_rollback: bool = False
) -> bool:
    """Close and forget one cached connection. Caller holds ``_db_lock``.

    The entry is popped *before* closing, so a concurrent ``_get_conn`` cannot be
    handed a connection that this call is in the middle of closing.

    ``reason`` is stamped onto the connection before it is closed (when it is one of
    ours), so if a live thread is still holding the reference and uses it later, the
    resulting :class:`ClosedDatabaseUseError` names which of the three close paths
    did it instead of just saying "closed".

    Returns True when a connection was actually closed, False when the entry was
    absent or skipped because the connection is mid-transaction.
    """
    conn = _connections.pop(key, None)
    _conn_last_used.pop(key, None)
    _conn_txn_since.pop(key, None)
    if conn is None:
        return False
    try:
        if conn.in_transaction:
            if not allow_rollback:
                # In-flight write transaction owned by another thread. Leave it
                # alone: close() would roll it back and lose the write. Put it back.
                _connections[key] = conn
                return False
            # The owner is provably gone (dead-thread sweep) or the caller has
            # already decided this is a leak. It can never be committed by anyone,
            # so roll it back -- that is the step that releases the SQLite write
            # lock -- before closing.
            conn.rollback()
    except Exception:  # pragma: no cover - a connection object that can't be asked
        pass
    marker = getattr(conn, "_ps_mark_closed", None)
    if marker is not None:
        try:
            marker(reason)
        except Exception:  # pragma: no cover - defensive
            pass
    try:
        conn.close()
    except Exception:
        pass
    return True


def close_db_connections(db_url: str | None = None) -> int:
    """Close cached SQLite connections, optionally scoped to one database URL.

    The app keeps one SQLite connection per thread for performance. On Windows,
    those open handles prevent temp database files from being deleted by tests
    and by short-lived maintenance scripts. This helper is safe to call during
    shutdown or test teardown; stale entries are removed from the cache even if
    an individual close raises.

    This is the ONE close path that is allowed to close a connection belonging to a
    thread that is still alive — it is an explicit "I am done with these" from the
    caller, and the runtime caller is ``atexit`` in app/services/ai_gateway.py. It
    stamps ``explicit_close_db_connections`` on each connection first, so if
    anything is still using one, the resulting error names this function rather
    than looking like a mystery.
    """
    closed = 0
    with _db_lock:
        keys = [
            key
            for key in list(_connections)
            if db_url is None or key.startswith(f"{db_url}:")
        ]
        for key in keys:
            conn = _connections.pop(key, None)
            _conn_last_used.pop(key, None)
            _conn_txn_since.pop(key, None)
            if conn is None:
                continue
            marker = getattr(conn, "_ps_mark_closed", None)
            if marker is not None:
                try:
                    marker("explicit_close_db_connections")
                except Exception:  # pragma: no cover - defensive
                    pass
            try:
                conn.close()
            except Exception:
                pass
            closed += 1
    return closed


def _retry_db_op(func, *args, max_retries: int = 3, **kwargs):
    """Retry a database operation on transient SQLite errors.

    Handles OperationalError (database locked, disk I/O) with
    exponential backoff. Non-retryable errors are raised immediately.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except sqlite3.OperationalError as exc:
            err_msg = str(exc).lower()
            # Only retry on transient errors
            if any(
                s in err_msg
                for s in (
                    "database is locked",
                    "disk i/o error",
                    "database disk image",
                    "attempt to write a readonly",
                )
            ):
                last_exc = exc
                delay = 0.1 * (2**attempt)
                _log.warning(
                    "DB retry %d/%d: %s (backoff %.2fs)",
                    attempt + 1,
                    max_retries,
                    exc,
                    delay,
                )
                time.sleep(delay)
                continue
            raise
    if last_exc is not None and is_locked_error(last_exc):
        # Recorded, not swallowed: this is the give-up point, and before this it
        # existed only as a warning in the journal.
        _record_contention(
            "locked_giveup",
            "database is locked (gave up at _retry_db_op after "
            f"{max_retries} attempts): {last_exc}",
            "_retry_db_op",
        )
    raise last_exc  # type: ignore[misc]


def init_db(db_url: str) -> None:
    """Create all tables if they don't exist."""
    conn = _get_conn(db_url)
    with _db_lock:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_conv_agent
                ON conversations(agent_id, created_at DESC);

            CREATE TABLE IF NOT EXISTS memories (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                source TEXT NOT NULL DEFAULT 'manual',
                content TEXT NOT NULL,
                tags_json TEXT DEFAULT '[]',
                importance INTEGER DEFAULT 5,
                category TEXT DEFAULT 'general',
                memory_type TEXT NOT NULL DEFAULT 'observation',
                access_count INTEGER NOT NULL DEFAULT 0,
                last_accessed_at TEXT,
                status TEXT NOT NULL DEFAULT 'active',
                superseded_by INTEGER REFERENCES memories(id),
                metadata_json TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_mem_agent
                ON memories(agent_id, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_mem_category
                ON memories(category, created_at DESC);

            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'open',
                priority TEXT NOT NULL DEFAULT 'medium',
                due_date TEXT,
                completed_at TEXT,
                assigned_to TEXT,
                delegated_from TEXT,
                mission_id INTEGER,
                tags_json TEXT DEFAULT '[]',
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_task_status
                ON tasks(status, priority, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_task_agent
                ON tasks(agent_id, status);
            CREATE INDEX IF NOT EXISTS idx_task_assigned
                ON tasks(assigned_to, status);

            CREATE TABLE IF NOT EXISTS knowledge (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                topic TEXT NOT NULL,
                content TEXT NOT NULL,
                source TEXT DEFAULT 'learned',
                confidence REAL DEFAULT 0.5,
                tags_json TEXT DEFAULT '[]',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_knowledge_topic
                ON knowledge(topic);
            CREATE INDEX IF NOT EXISTS idx_knowledge_agent
                ON knowledge(agent_id);

            CREATE TABLE IF NOT EXISTS credentials (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                service TEXT NOT NULL,
                key_name TEXT NOT NULL DEFAULT 'api_key',
                key_value TEXT NOT NULL,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(service, key_name)
            );

            CREATE TABLE IF NOT EXISTS settings_overrides (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cred_service
                ON credentials(service);

            CREATE INDEX IF NOT EXISTS idx_settings_overrides_updated
                ON settings_overrides(updated_at DESC);

            CREATE TABLE IF NOT EXISTS activity_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                action TEXT NOT NULL,
                detail TEXT DEFAULT '',
                details_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_activity_agent
                ON activity_log(agent_id, created_at DESC);

            -- Workforce: delegation tracking
            CREATE TABLE IF NOT EXISTS delegations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                from_agent_id TEXT NOT NULL,
                to_agent_id TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                reason TEXT DEFAULT '',
                result_summary TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_deleg_task
                ON delegations(task_id);
            CREATE INDEX IF NOT EXISTS idx_deleg_to
                ON delegations(to_agent_id, status);

            -- Workforce: agent performance metrics
            CREATE TABLE IF NOT EXISTS agent_metrics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL,
                metric_type TEXT NOT NULL,
                value REAL NOT NULL DEFAULT 0.0,
                period TEXT DEFAULT 'lifetime',
                details_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_metrics_agent
                ON agent_metrics(agent_id, metric_type);

            -- Evolution: code change log
            CREATE TABLE IF NOT EXISTS evolution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                change_type TEXT NOT NULL,
                description TEXT NOT NULL,
                files_changed TEXT DEFAULT '[]',
                proposal_id TEXT,
                applied INTEGER DEFAULT 0,
                rollback INTEGER DEFAULT 0,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_evolution_agent
                ON evolution_log(agent_id, created_at DESC);

            -- Evolution changelog (Round 2 A1.C — trust + recover + remember)
            -- Structured before/after with reasoning so VP can read the
            -- diary next session.  One row per applied evolution change.
            CREATE TABLE IF NOT EXISTS evolution_changelog (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                proposal_id TEXT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                file_path TEXT NOT NULL,
                change_summary TEXT NOT NULL,
                reasoning TEXT NOT NULL DEFAULT '',
                before_excerpt TEXT NOT NULL DEFAULT '',
                after_excerpt TEXT NOT NULL DEFAULT '',
                commit_sha TEXT,
                rolled_back INTEGER DEFAULT 0,
                rollback_reason TEXT,
                rolled_back_at TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_evo_changelog_created
                ON evolution_changelog(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_evo_changelog_file
                ON evolution_changelog(file_path, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_evo_changelog_rollback
                ON evolution_changelog(rolled_back, created_at DESC);

            -- VP inbox (Round 2 B1) — persistent queue between VP sessions.
            -- Populated by CoS/agents during VP-offline periods.
            -- Drained when VP comes online and reads the queue header.
            CREATE TABLE IF NOT EXISTS vp_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                kind TEXT NOT NULL,
                priority TEXT NOT NULL DEFAULT 'normal',
                title TEXT NOT NULL,
                body TEXT NOT NULL DEFAULT '',
                ref_type TEXT,
                ref_id TEXT,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                read_at TEXT,
                resolved_at TEXT,
                resolution_note TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vp_inbox_status
                ON vp_inbox(status, priority, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_vp_inbox_source
                ON vp_inbox(source, created_at DESC);

            -- SMS message log
            CREATE TABLE IF NOT EXISTS sms_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twilio_sid TEXT,
                direction TEXT NOT NULL DEFAULT 'outbound',
                from_number TEXT NOT NULL,
                to_number TEXT NOT NULL,
                body TEXT NOT NULL,
                template_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                error_message TEXT,
                agent_id TEXT DEFAULT 'orchestrator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sms_to
                ON sms_log(to_number, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_sms_sid
                ON sms_log(twilio_sid);
            CREATE INDEX IF NOT EXISTS idx_sms_status
                ON sms_log(status);

            -- SMS/MMS media attachments (inbound/outbound)
            CREATE TABLE IF NOT EXISTS sms_media (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_sid TEXT,
                direction TEXT NOT NULL DEFAULT 'inbound',
                from_number TEXT,
                to_number TEXT,
                media_index INTEGER DEFAULT 0,
                content_type TEXT,
                source_url TEXT,
                local_filename TEXT,
                file_bytes INTEGER DEFAULT 0,
                vision_summary TEXT,
                status TEXT NOT NULL DEFAULT 'saved',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_sms_media_msg
                ON sms_media(message_sid, media_index);
            CREATE INDEX IF NOT EXISTS idx_sms_media_created
                ON sms_media(created_at DESC);

            -- Voice notes (TTS-generated audio sent via Twilio MMS)
            CREATE TABLE IF NOT EXISTS voice_notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twilio_sid TEXT,
                recipient_name TEXT,
                recipient_phone TEXT NOT NULL,
                text_content TEXT NOT NULL,
                voice TEXT NOT NULL DEFAULT 'alloy',
                audio_filename TEXT,
                audio_url TEXT,
                duration_sec INTEGER,
                file_bytes INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'created',
                error_message TEXT,
                agent_id TEXT DEFAULT 'orchestrator',
                created_at TEXT NOT NULL,
                updated_at TEXT,
                sent_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_vn_recipient
                ON voice_notes(recipient_phone, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_vn_status
                ON voice_notes(status);
            CREATE INDEX IF NOT EXISTS idx_vn_created
                ON voice_notes(created_at DESC);

            -- Voice call recordings (Twilio)
            CREATE TABLE IF NOT EXISTS voice_recordings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT,
                recording_sid TEXT,
                from_number TEXT NOT NULL,
                to_number TEXT NOT NULL,
                duration_sec INTEGER DEFAULT 0,
                source_url TEXT,
                local_filename TEXT,
                status TEXT NOT NULL DEFAULT 'saved',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_voice_created
                ON voice_recordings(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_voice_call_sid
                ON voice_recordings(call_sid);

            -- Call log (inbound/outbound calls, with status updates)
            CREATE TABLE IF NOT EXISTS call_log (
                call_sid TEXT PRIMARY KEY,
                direction TEXT NOT NULL DEFAULT 'unknown',
                from_number TEXT NOT NULL,
                to_number TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'unknown',
                duration_sec INTEGER DEFAULT 0,
                recording_url TEXT,
                recording_sid TEXT,
                metadata_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_call_log_created
                ON call_log(created_at DESC);

            CREATE TABLE IF NOT EXISTS voice_handoff_requests (
                request_id TEXT PRIMARY KEY,
                call_sid TEXT NOT NULL,
                from_number TEXT NOT NULL,
                to_number TEXT NOT NULL,
                relationship TEXT NOT NULL DEFAULT 'unknown',
                caller_name TEXT DEFAULT '',
                reason TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                owner_notified INTEGER DEFAULT 0,
                poll_count INTEGER DEFAULT 0,
                owner_phone TEXT DEFAULT '',
                decision_token TEXT,
                decided_by TEXT,
                decided_at TEXT,
                expires_at REAL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_voice_handoff_call_sid
                ON voice_handoff_requests(call_sid, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_voice_handoff_status
                ON voice_handoff_requests(status, updated_at DESC);

            -- Voice transcripts (best-effort; may come from Twilio or a model)
            CREATE TABLE IF NOT EXISTS voice_transcripts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                call_sid TEXT,
                recording_sid TEXT,
                transcript_text TEXT NOT NULL,
                source TEXT DEFAULT 'unknown',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_voice_transcripts_call
                ON voice_transcripts(call_sid, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_voice_transcripts_recording
                ON voice_transcripts(recording_sid, created_at DESC);

            -- SMS opt-out list
            CREATE TABLE IF NOT EXISTS sms_opt_outs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                phone_number TEXT NOT NULL UNIQUE,
                reason TEXT DEFAULT 'STOP',
                created_at TEXT NOT NULL
            );

            -- Error log for self-healing
            CREATE TABLE IF NOT EXISTS error_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                error_type TEXT NOT NULL,
                error_message TEXT NOT NULL,
                traceback_text TEXT,
                endpoint TEXT,
                request_data TEXT,
                agent_id TEXT DEFAULT 'orchestrator',
                resolved INTEGER DEFAULT 0,
                resolution TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_error_unresolved
                ON error_log(resolved, created_at DESC);

            CREATE TABLE IF NOT EXISTS model_usage (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                provider TEXT NOT NULL,
                model TEXT NOT NULL,
                tier TEXT NOT NULL DEFAULT 'ceo',
                prompt_tokens INTEGER DEFAULT 0,
                completion_tokens INTEGER DEFAULT 0,
                total_tokens INTEGER DEFAULT 0,
                cached_tokens INTEGER DEFAULT 0,
                prompt_prefix_hash TEXT,
                served_by TEXT,
                session_id TEXT,
                estimated_cost_usd REAL DEFAULT 0.0,
                latency_ms INTEGER DEFAULT 0,
                success INTEGER DEFAULT 1,
                error_message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_model_usage_provider
                ON model_usage(provider, model, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_model_usage_tier
                ON model_usage(tier, created_at DESC);

            -- Long-running work tables

            CREATE TABLE IF NOT EXISTS work_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active',
                steps_completed INTEGER DEFAULT 0,
                total_steps INTEGER DEFAULT 0,
                progress_pct INTEGER DEFAULT 0,
                context_json TEXT DEFAULT '{}',
                output_log TEXT DEFAULT '',
                started_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                FOREIGN KEY (task_id) REFERENCES tasks(id)
            );

            CREATE INDEX IF NOT EXISTS idx_ws_status
                ON work_sessions(status, agent_id);
            CREATE INDEX IF NOT EXISTS idx_ws_task
                ON work_sessions(task_id);

            CREATE TABLE IF NOT EXISTS job_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                agent_id TEXT NOT NULL DEFAULT 'orchestrator',
                job_type TEXT NOT NULL,
                title TEXT NOT NULL DEFAULT '',
                payload_json TEXT DEFAULT '{}',
                status TEXT NOT NULL DEFAULT 'pending',
                priority INTEGER DEFAULT 5,
                retry_count INTEGER DEFAULT 0,
                max_retries INTEGER DEFAULT 3,
                error_message TEXT,
                result_json TEXT,
                created_at TEXT NOT NULL,
                picked_up_at TEXT,
                completed_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_jq_status
                ON job_queue(status, priority DESC, created_at ASC);
            CREATE INDEX IF NOT EXISTS idx_jq_agent
                ON job_queue(agent_id, status);

            CREATE TABLE IF NOT EXISTS progress_checkpoints (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                step_number INTEGER NOT NULL DEFAULT 0,
                label TEXT DEFAULT '',
                context_json TEXT DEFAULT '{}',
                output_text TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES work_sessions(id)
            );

            CREATE INDEX IF NOT EXISTS idx_pc_session
                ON progress_checkpoints(session_id, step_number);
        """)

        # ── Migrations ────────────────────────────────────
        # Add 'channel' column to conversations (chat/sms/autopilot)
        _safe_migrate(
            conn, "ALTER TABLE conversations ADD COLUMN channel TEXT DEFAULT 'chat'"
        )

        # Add agent attribution to model usage rows
        _safe_migrate(
            conn,
            "ALTER TABLE model_usage ADD COLUMN agent_id TEXT NOT NULL DEFAULT 'orchestrator'",
        )
        _safe_migrate(
            conn,
            "ALTER TABLE model_usage ADD COLUMN cached_tokens INTEGER DEFAULT 0",
        )
        _safe_migrate(
            conn,
            "ALTER TABLE model_usage ADD COLUMN prompt_prefix_hash TEXT",
        )
        _safe_migrate(
            conn,
            "ALTER TABLE model_usage ADD COLUMN served_by TEXT",
        )
        _safe_migrate(
            conn,
            "ALTER TABLE model_usage ADD COLUMN session_id TEXT",
        )
        _safe_migrate(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_model_usage_agent ON model_usage(agent_id, created_at DESC)",
        )
        _safe_migrate(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_model_usage_prefix_hash ON model_usage(prompt_prefix_hash, created_at DESC)",
        )
        _safe_migrate(
            conn,
            "CREATE INDEX IF NOT EXISTS idx_model_usage_session ON model_usage(session_id, created_at DESC)",
        )

        # Add long-running task fields to tasks table
        for col_sql in [
            "ALTER TABLE tasks ADD COLUMN parent_task_id INTEGER REFERENCES tasks(id)",
            "ALTER TABLE tasks ADD COLUMN progress_pct INTEGER DEFAULT 0",
            "ALTER TABLE tasks ADD COLUMN started_at TEXT",
            "ALTER TABLE tasks ADD COLUMN estimated_minutes INTEGER",
            "ALTER TABLE tasks ADD COLUMN mission_id INTEGER",
            "ALTER TABLE tasks ADD COLUMN dedupe_key TEXT",
        ]:
            _safe_migrate(conn, col_sql)

        # Index for mission alignment queries
        _safe_migrate(
            conn, "CREATE INDEX IF NOT EXISTS idx_task_mission ON tasks(mission_id)"
        )
        _safe_migrate(
            conn, "CREATE INDEX IF NOT EXISTS idx_task_dedupe_key ON tasks(dedupe_key)"
        )

        conn.commit()

        # ── Life-management tables (contacts, calendar, bills) ────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS contacts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                address TEXT,
                company TEXT,
                role TEXT,
                notes TEXT DEFAULT '',
                tags_json TEXT DEFAULT '[]',
                favorite INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_contacts_name
                ON contacts(name);
            CREATE INDEX IF NOT EXISTS idx_contacts_phone
                ON contacts(phone);
            CREATE INDEX IF NOT EXISTS idx_contacts_email
                ON contacts(email);

            CREATE TABLE IF NOT EXISTS contact_interactions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                contact_id INTEGER NOT NULL,
                channel TEXT NOT NULL DEFAULT 'unknown',
                direction TEXT NOT NULL DEFAULT 'inbound',
                summary TEXT DEFAULT '',
                ref_id TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                FOREIGN KEY (contact_id) REFERENCES contacts(id)
            );

            CREATE INDEX IF NOT EXISTS idx_ci_contact
                ON contact_interactions(contact_id);
            CREATE INDEX IF NOT EXISTS idx_ci_created
                ON contact_interactions(created_at);

            CREATE TABLE IF NOT EXISTS calendar_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                location TEXT DEFAULT '',
                start_time TEXT NOT NULL,
                end_time TEXT,
                all_day INTEGER DEFAULT 0,
                recurrence TEXT,
                reminder_minutes INTEGER DEFAULT 30,
                category TEXT DEFAULT 'general',
                tags_json TEXT DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'scheduled',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_cal_start
                ON calendar_events(start_time);
            CREATE INDEX IF NOT EXISTS idx_cal_status
                ON calendar_events(status);
            CREATE INDEX IF NOT EXISTS idx_cal_category
                ON calendar_events(category);

            CREATE TABLE IF NOT EXISTS bills (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                provider TEXT DEFAULT '',
                amount REAL,
                currency TEXT DEFAULT 'USD',
                due_date TEXT,
                recurrence TEXT DEFAULT 'monthly',
                category TEXT DEFAULT 'general',
                auto_pay INTEGER DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'pending',
                paid_date TEXT,
                notes TEXT DEFAULT '',
                url TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_bills_due
                ON bills(due_date);
            CREATE INDEX IF NOT EXISTS idx_bills_status
                ON bills(status);
            CREATE INDEX IF NOT EXISTS idx_bills_category
                ON bills(category);

            CREATE TABLE IF NOT EXISTS web_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                site_name TEXT NOT NULL,
                site_url TEXT NOT NULL,
                storage_state_path TEXT NOT NULL,
                username TEXT DEFAULT '',
                notes TEXT DEFAULT '',
                last_used TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(site_name)
            );

            CREATE INDEX IF NOT EXISTS idx_websess_site
                ON web_sessions(site_name);
        """)
        conn.commit()

        # ── Contact enrichment columns (migration) ───────────
        for col_sql in [
            "ALTER TABLE contacts ADD COLUMN last_interaction TEXT",
            "ALTER TABLE contacts ADD COLUMN interaction_count INTEGER DEFAULT 0",
            "ALTER TABLE contacts ADD COLUMN relationship TEXT DEFAULT ''",
            "ALTER TABLE contacts ADD COLUMN source TEXT DEFAULT 'manual'",
        ]:
            _safe_migrate(conn, col_sql)

        # ── Missions / OKR table ──────────────────────────────
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS missions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                key_results TEXT DEFAULT '',
                timeframe TEXT DEFAULT 'month',
                status TEXT NOT NULL DEFAULT 'proposed',
                progress_pct INTEGER DEFAULT 0,
                proposed_by TEXT DEFAULT 'orchestrator',
                approved_at TEXT,
                notes TEXT DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_missions_status
                ON missions(status);

            CREATE TABLE IF NOT EXISTS owner_profile (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL UNIQUE,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                source TEXT DEFAULT 'inferred',
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_owner_profile_key
                ON owner_profile(key);

            CREATE TABLE IF NOT EXISTS owner_assumptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                key TEXT NOT NULL,
                value TEXT NOT NULL,
                confidence REAL DEFAULT 0.5,
                evidence TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'proposed',
                proposed_by TEXT DEFAULT 'orchestrator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                confirmed_at TEXT,
                rejected_at TEXT
            );

            CREATE INDEX IF NOT EXISTS idx_owner_assumptions_status
                ON owner_assumptions(status, updated_at DESC);
            CREATE INDEX IF NOT EXISTS idx_owner_assumptions_key
                ON owner_assumptions(key);

            CREATE TABLE IF NOT EXISTS spend_requests (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                vendor TEXT DEFAULT '',
                amount_usd REAL,
                currency TEXT DEFAULT 'USD',
                status TEXT NOT NULL DEFAULT 'proposed',
                requested_by TEXT DEFAULT 'orchestrator',
                approved_at TEXT,
                rejected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_spend_status
                ON spend_requests(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS human_jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                description TEXT DEFAULT '',
                platform TEXT DEFAULT 'upwork',
                budget_usd REAL,
                status TEXT NOT NULL DEFAULT 'draft',
                job_post_text TEXT DEFAULT '',
                requested_by TEXT DEFAULT 'orchestrator',
                approved_at TEXT,
                rejected_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_human_jobs_status
                ON human_jobs(status, updated_at DESC);

            CREATE TABLE IF NOT EXISTS owner_feedback_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER,
                payload_json TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS owner_weekly_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                week_key TEXT NOT NULL UNIQUE,
                score INTEGER NOT NULL,
                comment TEXT DEFAULT '',
                source TEXT DEFAULT 'sms',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_owner_feedback_created
                ON owner_feedback_events(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_owner_feedback_type
                ON owner_feedback_events(event_type, created_at DESC);

            CREATE INDEX IF NOT EXISTS idx_owner_weekly_feedback_week
                ON owner_weekly_feedback(week_key);
            CREATE INDEX IF NOT EXISTS idx_owner_weekly_feedback_created
                ON owner_weekly_feedback(created_at DESC);

            CREATE TABLE IF NOT EXISTS owner_message_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                reason TEXT DEFAULT '',
                urgency TEXT DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                sent_at TEXT,
                repeat_count INTEGER DEFAULT 1,
                last_seen_at TEXT,
                deliver_on_inbound INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_owner_msg_status
                ON owner_message_queue(status, created_at DESC);

            CREATE TABLE IF NOT EXISTS captures_inbox (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                raw_text TEXT NOT NULL,
                normalized_text TEXT DEFAULT '',
                kind TEXT NOT NULL DEFAULT 'note',
                status TEXT NOT NULL DEFAULT 'captured',
                confidence REAL DEFAULT 0.0,
                source_channel TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT DEFAULT '',
                sensitivity TEXT NOT NULL DEFAULT 'normal',
                owner_needed INTEGER NOT NULL DEFAULT 0,
                routed_to_json TEXT DEFAULT '{}',
                metadata_json TEXT DEFAULT '{}',
                expires_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_captures_status
                ON captures_inbox(status, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_captures_kind
                ON captures_inbox(kind, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_captures_source
                ON captures_inbox(source_channel, source_ref);

            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                scheduled_time TEXT NOT NULL,
                source TEXT NOT NULL DEFAULT 'manual',
                source_ref TEXT DEFAULT '',
                status TEXT NOT NULL DEFAULT 'pending',
                priority TEXT NOT NULL DEFAULT 'normal',
                requires_ack INTEGER NOT NULL DEFAULT 1,
                snooze_until TEXT,
                recurrence TEXT,
                delivery_channel TEXT NOT NULL DEFAULT 'dashboard',
                delivery_attempts INTEGER NOT NULL DEFAULT 0,
                last_delivered_at TEXT,
                quiet_hours_override INTEGER NOT NULL DEFAULT 0,
                metadata_json TEXT DEFAULT '{}',
                legacy_id TEXT UNIQUE,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_reminders_due
                ON reminders(status, scheduled_time);
            CREATE INDEX IF NOT EXISTS idx_reminders_source
                ON reminders(source, source_ref);
            CREATE INDEX IF NOT EXISTS idx_reminders_status
                ON reminders(status, updated_at DESC);

            -- Delegation execution attempts (external integrations)
            CREATE TABLE IF NOT EXISTS delegation_execution_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type TEXT NOT NULL,
                target_type TEXT NOT NULL,
                target_id INTEGER,
                request_json TEXT DEFAULT '{}',
                response_json TEXT DEFAULT '{}',
                ok INTEGER DEFAULT 0,
                error_message TEXT,
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_deleg_exec_created
                ON delegation_execution_log(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_deleg_exec_target
                ON delegation_execution_log(target_type, target_id, created_at DESC);

            -- Real-time owner/user state (event-driven context)
            CREATE TABLE IF NOT EXISTS owner_state (
                key TEXT PRIMARY KEY,
                value_json TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_owner_state_updated
                ON owner_state(updated_at DESC);

            CREATE TABLE IF NOT EXISTS event_triage_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                source TEXT NOT NULL,
                event_type TEXT NOT NULL,
                summary TEXT NOT NULL,
                classification TEXT NOT NULL DEFAULT 'ignore',
                action_taken TEXT DEFAULT '',
                raw_data TEXT DEFAULT '{}',
                created_at TEXT NOT NULL
            );

            CREATE INDEX IF NOT EXISTS idx_triage_source
                ON event_triage_log(source, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_triage_class
                ON event_triage_log(classification, created_at DESC);

            -- Phase 2: memory_entries for sqlite-vec hybrid search
            CREATE TABLE IF NOT EXISTS memory_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT DEFAULT 'general',
                tags TEXT DEFAULT '[]',
                agent_id TEXT DEFAULT 'orchestrator',
                source TEXT DEFAULT 'manual',
                importance INTEGER DEFAULT 5,
                created_at TEXT DEFAULT (datetime('now')),
                updated_at TEXT DEFAULT (datetime('now'))
            );

            CREATE INDEX IF NOT EXISTS idx_memory_entries_category
                ON memory_entries(category, created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_memory_entries_agent
                ON memory_entries(agent_id, created_at DESC);

            -- Phase 2: briefing_log for pre-meeting briefings
            CREATE TABLE IF NOT EXISTS briefing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id TEXT NOT NULL,
                briefing_type TEXT NOT NULL DEFAULT 'meeting',
                content TEXT NOT NULL,
                sent_at TEXT NOT NULL,
                UNIQUE(event_id, briefing_type)
            );

            CREATE INDEX IF NOT EXISTS idx_briefing_event
                ON briefing_log(event_id);

            -- ── Workflow engine tables (Phase 8: Goal Persistence) ──

            CREATE TABLE IF NOT EXISTS goal_plans (
                id              TEXT PRIMARY KEY,
                parent_goal_id  TEXT REFERENCES goal_plans(id),
                title           TEXT NOT NULL,
                objective       TEXT NOT NULL DEFAULT '',
                priority        INTEGER DEFAULT 50 CHECK(priority BETWEEN 0 AND 100),
                status          TEXT NOT NULL DEFAULT 'active'
                                CHECK(status IN ('active','paused','completed','failed','cancelled')),
                source          TEXT NOT NULL DEFAULT 'ceo',
                source_ref      TEXT,
                assigned_agent  TEXT DEFAULT 'orchestrator',
                context_json    TEXT DEFAULT '{}',
                plan_json       TEXT,
                progress_pct    INTEGER DEFAULT 0,
                created_at      TEXT NOT NULL DEFAULT (datetime('now')),
                updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
                completed_at    TEXT,
                deadline        TEXT,
                estimated_ticks INTEGER,
                actual_ticks    INTEGER DEFAULT 0
            );

            CREATE INDEX IF NOT EXISTS idx_goal_plans_status
                ON goal_plans(status);
            CREATE INDEX IF NOT EXISTS idx_goal_plans_agent
                ON goal_plans(assigned_agent);

            CREATE TABLE IF NOT EXISTS goal_steps (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                goal_id         TEXT NOT NULL REFERENCES goal_plans(id) ON DELETE CASCADE,
                step_number     INTEGER NOT NULL,
                title           TEXT NOT NULL,
                description     TEXT DEFAULT '',
                status          TEXT NOT NULL DEFAULT 'pending'
                                CHECK(status IN ('pending','running','waiting_approval',
                                                 'completed','failed','skipped','blocked')),
                assigned_agent  TEXT,
                input_json      TEXT DEFAULT '{}',
                output_json     TEXT,
                error_message   TEXT,
                attempts        INTEGER DEFAULT 0,
                max_retries     INTEGER DEFAULT 3,
                requires_approval INTEGER DEFAULT 0,
                started_at      TEXT,
                completed_at    TEXT,
                UNIQUE(goal_id, step_number)
            );

            CREATE INDEX IF NOT EXISTS idx_goal_steps_status
                ON goal_steps(goal_id, status);
            CREATE INDEX IF NOT EXISTS idx_goal_steps_next
                ON goal_steps(goal_id, step_number);

            CREATE TABLE IF NOT EXISTS agent_working_memory (
                agent_id        TEXT PRIMARY KEY,
                tick_number     INTEGER NOT NULL DEFAULT 0,
                active_focus    TEXT,
                next_actions    TEXT DEFAULT '[]',
                decisions_log   TEXT DEFAULT '[]',
                context_summary TEXT,
                updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
            );

            -- Directive 007: Event-driven reactive pipeline
            CREATE TABLE IF NOT EXISTS events (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                event_type      TEXT NOT NULL,
                source          TEXT NOT NULL,
                source_id       TEXT,
                priority        INTEGER NOT NULL DEFAULT 2,
                payload         TEXT NOT NULL DEFAULT '{}',
                status          TEXT NOT NULL DEFAULT 'pending',
                created_at      TEXT NOT NULL,
                claimed_at      TEXT,
                processed_at    TEXT,
                attempts        INTEGER NOT NULL DEFAULT 0,
                max_attempts    INTEGER NOT NULL DEFAULT 3,
                next_attempt_at TEXT,
                dedup_key       TEXT,
                error_message   TEXT,
                correlation_id  TEXT
            );
            CREATE UNIQUE INDEX IF NOT EXISTS idx_events_dedup
                ON events(dedup_key) WHERE dedup_key IS NOT NULL;
            CREATE INDEX IF NOT EXISTS idx_events_dequeue
                ON events(status, priority, created_at);

            CREATE TABLE IF NOT EXISTS step_trigger_state (
                step_id      INTEGER NOT NULL,
                condition_id TEXT NOT NULL,
                fulfilled    INTEGER NOT NULL DEFAULT 0,
                fulfilled_at TEXT,
                event_id     INTEGER,
                PRIMARY KEY (step_id, condition_id)
            );

            CREATE TABLE IF NOT EXISTS routing_log (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                event_id    INTEGER NOT NULL,
                priority    INTEGER,
                rule_id     TEXT,
                method      TEXT NOT NULL,
                confidence  REAL,
                action      TEXT,
                actor       TEXT,
                latency_ms  REAL,
                created_at  TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_routing_log_event
                ON routing_log(event_id);

            -- ── Directive 008: Autonomous work generation ──

            CREATE TABLE IF NOT EXISTS standing_work_orders (
                id                    TEXT PRIMARY KEY,
                department            TEXT NOT NULL,
                task_type             TEXT NOT NULL,
                description           TEXT,
                schedule_type         TEXT NOT NULL
                                      CHECK(schedule_type IN ('interval','daily','cron')),
                interval_minutes      INTEGER,
                scheduled_hour        INTEGER,
                scheduled_minute      INTEGER DEFAULT 0,
                cron_expression       TEXT,
                last_run_at           TEXT,
                last_run_status       TEXT
                                      CHECK(last_run_status IN
                                            ('success','failed','running','skipped')),
                next_run_after        TEXT NOT NULL,
                is_enabled            INTEGER DEFAULT 1,
                coalesce              INTEGER DEFAULT 1,
                misfire_grace_minutes INTEGER DEFAULT 30,
                priority              INTEGER DEFAULT 2 CHECK(priority BETWEEN 0 AND 3),
                goal_template_json    TEXT NOT NULL,
                created_at            TEXT DEFAULT (datetime('now')),
                UNIQUE(department, task_type)
            );

            CREATE TABLE IF NOT EXISTS work_order_executions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                work_order_id   TEXT NOT NULL REFERENCES standing_work_orders(id),
                goal_plan_id    TEXT,
                scheduled_for   TEXT NOT NULL,
                started_at      TEXT,
                completed_at    TEXT,
                status          TEXT CHECK(status IN
                                     ('pending','running','success','failed','skipped')),
                error_message   TEXT,
                UNIQUE(work_order_id, scheduled_for)
            );

            CREATE TABLE IF NOT EXISTS trigger_goal_templates (
                id                     INTEGER PRIMARY KEY AUTOINCREMENT,
                trigger_type           TEXT NOT NULL,
                template_name          TEXT NOT NULL,
                goal_title_template    TEXT NOT NULL,
                department             TEXT NOT NULL,
                priority               INTEGER DEFAULT 50,
                confidence_threshold   REAL DEFAULT 0.7,
                auto_execute_threshold REAL DEFAULT 0.9,
                cooldown_seconds       INTEGER DEFAULT 3600,
                steps_json             TEXT NOT NULL,
                conditions_json        TEXT,
                enabled                INTEGER DEFAULT 1,
                success_count          INTEGER DEFAULT 0,
                failure_count          INTEGER DEFAULT 0,
                created_at             TEXT DEFAULT (datetime('now')),
                UNIQUE(trigger_type, template_name)
            );

            CREATE TABLE IF NOT EXISTS trigger_dedup_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                dedup_key       TEXT NOT NULL UNIQUE,
                trigger_type    TEXT NOT NULL,
                goal_plan_id    TEXT,
                status          TEXT DEFAULT 'active',
                created_at      TEXT DEFAULT (datetime('now')),
                expires_at      TEXT,
                last_trigger_at TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_trigger_dedup_status
                ON trigger_dedup_log(dedup_key, status);

            CREATE TABLE IF NOT EXISTS tick_activity (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                tick_number INTEGER NOT NULL,
                agent_id    TEXT NOT NULL,
                was_active  INTEGER DEFAULT 0,
                action_type TEXT,
                step_id     INTEGER,
                goal_id     TEXT,
                tokens_in   INTEGER DEFAULT 0,
                tokens_out  INTEGER DEFAULT 0,
                cost_usd    REAL DEFAULT 0.0,
                duration_ms INTEGER DEFAULT 0,
                created_at  TEXT DEFAULT (datetime('now')),
                UNIQUE(tick_number, agent_id)
            );
            CREATE INDEX IF NOT EXISTS idx_tick_activity_agent
                ON tick_activity(agent_id, created_at);

            -- Directive 009: action approval queue for autonomy gating
            CREATE TABLE IF NOT EXISTS action_approval_queue (
                id          TEXT PRIMARY KEY,
                agent_id    TEXT NOT NULL,
                step_id     INTEGER,
                goal_id     TEXT,
                tool_name   TEXT NOT NULL,
                arguments   TEXT NOT NULL DEFAULT '{}',
                context_json TEXT DEFAULT '{}',
                autonomy_level INTEGER DEFAULT 0,
                status      TEXT DEFAULT 'pending'
                                CHECK(status IN ('pending','approved','rejected',
                                                 'executed','expired')),
                created_at  TEXT DEFAULT (datetime('now')),
                resolved_at TEXT,
                resolved_by TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_approval_queue_status
                ON action_approval_queue(status, created_at);
            CREATE INDEX IF NOT EXISTS idx_approval_queue_agent
                ON action_approval_queue(agent_id, status);

            -- Daily reconciliation: run history
            CREATE TABLE IF NOT EXISTS reconciliation_runs (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TEXT NOT NULL,
                finished_at     TEXT,
                status          TEXT NOT NULL DEFAULT 'running'
                                  CHECK(status IN ('running','ok','error')),
                trigger         TEXT NOT NULL DEFAULT 'autopilot',
                model           TEXT,
                evidence_summary_json TEXT DEFAULT '{}',
                proposals_total INTEGER DEFAULT 0,
                auto_executed   INTEGER DEFAULT 0,
                queued_review   INTEGER DEFAULT 0,
                dropped         INTEGER DEFAULT 0,
                error           TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_recon_runs_started
                ON reconciliation_runs(started_at);

            -- Daily reconciliation: per-proposal record (review queue)
            CREATE TABLE IF NOT EXISTS reconciliation_proposals (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER REFERENCES reconciliation_runs(id),
                created_at      TEXT NOT NULL,
                action_type     TEXT NOT NULL,
                target          TEXT,
                payload_json    TEXT NOT NULL DEFAULT '{}',
                rationale       TEXT,
                evidence_refs_json TEXT DEFAULT '[]',
                confidence      REAL NOT NULL,
                disposition     TEXT NOT NULL DEFAULT 'queued'
                                  CHECK(disposition IN
                                        ('queued','auto_executed','dropped',
                                         'approved','rejected','failed')),
                resolved_at     TEXT,
                resolved_by     TEXT,
                execution_result_json TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_recon_props_disposition
                ON reconciliation_proposals(disposition, created_at);
            CREATE INDEX IF NOT EXISTS idx_recon_props_run
                ON reconciliation_proposals(run_id);

            -- Phone & Tech chat-agent review: run history.
            CREATE TABLE IF NOT EXISTS chat_agent_review_runs (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at          TEXT NOT NULL,
                finished_at         TEXT,
                status              TEXT NOT NULL DEFAULT 'running'
                                      CHECK(status IN
                                            ('running','ok','partial','error')),
                trigger             TEXT NOT NULL DEFAULT 'manual',
                review_window_start TEXT,
                review_window_end   TEXT,
                archive_path        TEXT,
                audit_log_path      TEXT,
                sources_json        TEXT DEFAULT '{}',
                kpis_json           TEXT DEFAULT '{}',
                findings_json       TEXT DEFAULT '[]',
                auto_actions        INTEGER DEFAULT 0,
                queued_actions      INTEGER DEFAULT 0,
                error               TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chat_agent_review_runs_status
                ON chat_agent_review_runs(status, started_at);
            CREATE INDEX IF NOT EXISTS idx_chat_agent_review_runs_finished
                ON chat_agent_review_runs(finished_at);

            -- Phone & Tech chat-agent review: auto/queued action audit log.
            CREATE TABLE IF NOT EXISTS chat_agent_review_actions (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id          INTEGER REFERENCES chat_agent_review_runs(id),
                created_at      TEXT NOT NULL,
                action_type     TEXT NOT NULL,
                autonomy_level  INTEGER NOT NULL DEFAULT 4,
                target          TEXT,
                payload_json    TEXT NOT NULL DEFAULT '{}',
                confidence      REAL,
                dollar_delta    REAL,
                sources_json    TEXT DEFAULT '[]',
                status          TEXT NOT NULL DEFAULT 'queued'
                                  CHECK(status IN
                                        ('planned','queued','auto_applied',
                                         'owner_approval','blocked','failed',
                                         'skipped')),
                undo_json       TEXT DEFAULT '{}',
                result_json     TEXT DEFAULT '{}',
                error           TEXT,
                resolved_at     TEXT,
                resolved_by     TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_chat_agent_review_actions_run
                ON chat_agent_review_actions(run_id);
            CREATE INDEX IF NOT EXISTS idx_chat_agent_review_actions_status
                ON chat_agent_review_actions(status, created_at);

            -- Dialpad transcript + recap cache.
            -- Persisted across runs so reconciliation rebuilds the full
            -- per-customer narrative without re-hammering the API and
            -- without losing transcripts on calls outside the current
            -- 14-30 day window.
            CREATE TABLE IF NOT EXISTS dialpad_transcript_cache (
                call_id          TEXT PRIMARY KEY,
                phone_normalized TEXT,
                started_at       TEXT,
                direction        TEXT,
                duration_seconds INTEGER,
                state            TEXT,
                transcript_text  TEXT,
                recap_text       TEXT,
                has_transcript   INTEGER NOT NULL DEFAULT 0,
                has_recap        INTEGER NOT NULL DEFAULT 0,
                transcript_attempted_at TEXT,
                recap_attempted_at      TEXT,
                attempts         INTEGER NOT NULL DEFAULT 0,
                fetched_at       TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_dpt_phone
                ON dialpad_transcript_cache(phone_normalized, started_at);
            CREATE INDEX IF NOT EXISTS idx_dpt_recap_pending
                ON dialpad_transcript_cache(has_recap, recap_attempted_at);

            -- Dialpad SMS / digital session message cache.
            -- One row per individual message inside a digital session,
            -- so we keep the actual SMS body text per customer thread.
            CREATE TABLE IF NOT EXISTS dialpad_sms_cache (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id       TEXT NOT NULL,
                message_id       TEXT,
                phone_normalized TEXT,
                customer_name    TEXT,
                channel          TEXT,
                direction        TEXT,
                created_at       TEXT,
                body_text        TEXT,
                fetched_at       TEXT NOT NULL,
                UNIQUE(session_id, message_id)
            );
            CREATE INDEX IF NOT EXISTS idx_dpsms_phone
                ON dialpad_sms_cache(phone_normalized, created_at);
            -- The ingest guard in dialpad_service._write_sms_cache asks
            -- "does this message already exist for this direction?" on every
            -- write.  Without this index that is a full scan of 136k rows under
            -- _db_lock; with it, a lookup.  Deliberately NOT unique: 3,990
            -- pre-existing duplicate groups (measured 2026-10-21) would make a
            -- unique index unbuildable, and deleting them is forbidden.
            CREATE INDEX IF NOT EXISTS idx_dpsms_message
                ON dialpad_sms_cache(message_id, direction);
        """)
        conn.commit()

    # ── Unified comms identity cross-reference table ──
    # Links all the different session/thread ID formats to normalized
    # phone numbers so the reconciliation can join across sources.
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS comms_identity_link (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            phone_normalized TEXT NOT NULL,
            source          TEXT NOT NULL CHECK(source IN (
                'dialpad_sms_cache','dialpad_call_full','dialpad_digital_session',
                'dialpad_ui_message','dialpad_ui_message_body',
                'ptf_backfill','dialpad_call_link','manual'
            )),
            source_id       TEXT NOT NULL,
            customer_name   TEXT,
            first_seen_at   TEXT NOT NULL,
            last_seen_at    TEXT NOT NULL,
            UNIQUE(source, source_id)
        );
        CREATE INDEX IF NOT EXISTS idx_cil_phone
            ON comms_identity_link(phone_normalized);
        CREATE INDEX IF NOT EXISTS idx_cil_source
            ON comms_identity_link(source, last_seen_at);
    """)
    conn.commit()

    # ── Memory table upgrades (Directive 006: unified memory) ──
    for _col_sql in [
        "ALTER TABLE memories ADD COLUMN memory_type TEXT NOT NULL DEFAULT 'observation'",
        "ALTER TABLE memories ADD COLUMN access_count INTEGER NOT NULL DEFAULT 0",
        "ALTER TABLE memories ADD COLUMN last_accessed_at TEXT",
        "ALTER TABLE memories ADD COLUMN status TEXT NOT NULL DEFAULT 'active'",
        "ALTER TABLE memories ADD COLUMN superseded_by INTEGER REFERENCES memories(id)",
        "ALTER TABLE memories ADD COLUMN metadata_json TEXT",
    ]:
        _safe_migrate(conn, _col_sql)

    for _ix_sql in [
        "CREATE INDEX IF NOT EXISTS idx_mem_status ON memories(status, last_accessed_at)",
        "CREATE INDEX IF NOT EXISTS idx_mem_type ON memories(memory_type, status)",
    ]:
        _safe_migrate(conn, _ix_sql)

    # ── Goal step config column (Directive 007: event triggers) ──
    _safe_migrate(
        conn, "ALTER TABLE goal_steps ADD COLUMN config_json TEXT DEFAULT '{}'"
    )

    # ── Directive 008: goal_plans evergreen + goal_steps claim columns ──
    for _col_sql in [
        "ALTER TABLE goal_plans ADD COLUMN is_evergreen INTEGER DEFAULT 0",
        "ALTER TABLE goal_plans ADD COLUMN cooldown_minutes INTEGER",
        "ALTER TABLE goal_steps ADD COLUMN claimed_by TEXT",
        "ALTER TABLE goal_steps ADD COLUMN result_summary TEXT",
    ]:
        _safe_migrate(conn, _col_sql)

    # ── Directive 009: goal_plans origin tracking columns ──
    for _col_sql in [
        "ALTER TABLE goal_plans ADD COLUMN origin_source TEXT DEFAULT 'manual'",
        "ALTER TABLE goal_plans ADD COLUMN parent_task_id INTEGER",
    ]:
        _safe_migrate(conn, _col_sql)

    # ── Directive 010: LLM Cost Hardening & Agent Observability ──

    conn.executescript("""
        -- Circuit breaker event log
        CREATE TABLE IF NOT EXISTS circuit_breaker_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT,
            event_type      TEXT NOT NULL,
            reason          TEXT,
            spend_at_event  REAL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cb_events_agent
            ON circuit_breaker_events(agent_id, created_at);

        -- Circuit breaker live state (persisted so trips survive restarts)
        CREATE TABLE IF NOT EXISTS circuit_breaker_state (
            agent_id        TEXT PRIMARY KEY,
            state           TEXT NOT NULL DEFAULT 'closed',
            cooldown_until  REAL,
            tripped_at      REAL,
            reason          TEXT,
            failure_count   INTEGER NOT NULL DEFAULT 0,
            cooldown_sec    INTEGER NOT NULL DEFAULT 0,
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        -- Deferred LLM work queue (tiered enforcement park-and-resume)
        CREATE TABLE IF NOT EXISTS deferred_llm_work (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            work_type       TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'P2',
            pool            TEXT NOT NULL DEFAULT 'company',
            payload         TEXT NOT NULL DEFAULT '{}',
            reason          TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            max_attempts    INTEGER NOT NULL DEFAULT 5,
            next_attempt_at TEXT NOT NULL,
            dedup_key       TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_deferred_work_due
            ON deferred_llm_work(status, next_attempt_at);
        CREATE INDEX IF NOT EXISTS idx_deferred_work_dedup
            ON deferred_llm_work(dedup_key, status);

        -- Detailed tick telemetry for observability
        CREATE TABLE IF NOT EXISTS tick_telemetry (
            id                      INTEGER PRIMARY KEY AUTOINCREMENT,
            tick_id                 TEXT NOT NULL,
            agent_id                TEXT NOT NULL,
            tick_number             INTEGER DEFAULT 0,
            step_id                 INTEGER,
            goal_id                 TEXT,
            started_at              TEXT NOT NULL,
            ended_at                TEXT,
            llm_rounds              INTEGER DEFAULT 0,
            total_tokens            INTEGER DEFAULT 0,
            total_cost              REAL DEFAULT 0.0,
            tool_calls_json         TEXT DEFAULT '[]',
            autonomy_decisions_json TEXT DEFAULT '[]',
            latency_ms              REAL DEFAULT 0.0,
            steps_completed         INTEGER DEFAULT 0,
            outcome                 TEXT,
            error                   TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_tt_agent_started
            ON tick_telemetry(agent_id, started_at);

        -- Spend anomaly tracking
        CREATE TABLE IF NOT EXISTS anomaly_log (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id       TEXT NOT NULL,
            anomaly_type   TEXT NOT NULL,
            detail         TEXT,
            severity       REAL DEFAULT 1.0,
            escalation     TEXT DEFAULT 'logged',
            detected_at    TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_anomaly_agent_time
            ON anomaly_log(agent_id, detected_at);

        -- Covering index for velocity queries on model_usage
        CREATE INDEX IF NOT EXISTS idx_usage_velocity
            ON model_usage(agent_id, created_at, estimated_cost_usd);

        -- Directive 012: blocked agents (phantom-spawn prevention)
        CREATE TABLE IF NOT EXISTS blocked_agents (
            agent_id    TEXT PRIMARY KEY,
            blocked_at  TEXT NOT NULL DEFAULT (datetime('now')),
            reason      TEXT
        );
        """)
    conn.commit()

    # ── Directive 013: Goal Lifecycle & Output Verification ──────
    for _tbl, _col, _ctype in [
        ("tick_telemetry", "tick_quality", "TEXT DEFAULT 'unknown'"),
        ("goal_steps", "last_heartbeat_at", "TEXT"),
        ("goal_plans", "superseded_by", "TEXT"),
    ]:
        try:
            conn.execute(f"ALTER TABLE {_tbl} ADD COLUMN {_col} {_ctype}")
            conn.commit()
        except Exception:  # noqa: BLE001
            pass  # Column already exists
    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_goals_active_updated
            ON goal_plans(status, updated_at)
            WHERE status IN ('active', 'paused');
        CREATE INDEX IF NOT EXISTS idx_steps_running_heartbeat
            ON goal_steps(status, last_heartbeat_at)
            WHERE status = 'running';
    """)
    conn.commit()

    # ── Directive 014: Email Triage Pipeline ────────────────────
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS email_triage_log (
            id                     INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id             TEXT NOT NULL,
            thread_id              TEXT NOT NULL,
            account_email          TEXT NOT NULL,
            sender                 TEXT NOT NULL DEFAULT '',
            subject                TEXT NOT NULL DEFAULT '',
            category               TEXT NOT NULL,
            sub_category           TEXT,
            confidence_score       REAL CHECK(confidence_score BETWEEN 0.0 AND 1.0),
            confidence_tier        TEXT CHECK(confidence_tier IN ('high','medium','low')),
            classification_method  TEXT NOT NULL DEFAULT 'rules',
            action_taken           TEXT NOT NULL DEFAULT 'none',
            action_status          TEXT NOT NULL DEFAULT 'pending',
            tags_json              TEXT DEFAULT '[]',
            draft_id               TEXT,
            error_message          TEXT,
            model_used             TEXT,
            processing_duration_ms INTEGER,
            metadata_json          TEXT DEFAULT '{}',
            created_at             TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_triage_dedup
            ON email_triage_log(message_id, account_email);
        CREATE INDEX IF NOT EXISTS idx_triage_thread
            ON email_triage_log(thread_id, account_email);
        CREATE INDEX IF NOT EXISTS idx_triage_pending
            ON email_triage_log(action_status)
            WHERE action_status NOT IN ('completed','skipped');
        CREATE INDEX IF NOT EXISTS idx_triage_category
            ON email_triage_log(category, created_at DESC);

        CREATE TABLE IF NOT EXISTS email_thread_state (
            thread_id         TEXT NOT NULL,
            account_email     TEXT NOT NULL,
            status            TEXT NOT NULL DEFAULT 'new',
            message_count     INTEGER NOT NULL DEFAULT 0,
            last_message_at   TEXT,
            last_sender       TEXT,
            last_category     TEXT,
            needs_response    INTEGER NOT NULL DEFAULT 0,
            contact_id        TEXT,
            relationship      TEXT,
            updated_at        TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            PRIMARY KEY (thread_id, account_email)
        );

        CREATE TABLE IF NOT EXISTS google_voice_secretary_log (
            item_hash         TEXT PRIMARY KEY,
            account_index     INTEGER NOT NULL,
            item_type         TEXT NOT NULL,
            contact           TEXT NOT NULL DEFAULT '',
            item_timestamp    TEXT NOT NULL DEFAULT '',
            summary           TEXT NOT NULL DEFAULT '',
            decision          TEXT NOT NULL DEFAULT 'owner_review',
            confidence        REAL NOT NULL DEFAULT 0.0,
            action_status     TEXT NOT NULL DEFAULT 'pending_review',
            reply_text        TEXT NOT NULL DEFAULT '',
            owner_question_id TEXT NOT NULL DEFAULT '',
            payload_json      TEXT NOT NULL DEFAULT '{}',
            created_at        TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at        TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS email_drafts (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            account_email       TEXT NOT NULL,
            gmail_draft_id      TEXT,
            thread_id           TEXT NOT NULL,
            original_message_id TEXT NOT NULL,
            original_from       TEXT NOT NULL DEFAULT '',
            original_subject    TEXT NOT NULL DEFAULT '',
            subject             TEXT NOT NULL DEFAULT '',
            body_plain          TEXT NOT NULL DEFAULT '',
            body_html           TEXT NOT NULL DEFAULT '',
            to_addresses_json   TEXT NOT NULL DEFAULT '[]',
            in_reply_to         TEXT NOT NULL DEFAULT '',
            references_header   TEXT NOT NULL DEFAULT '',
            style_profile_id    TEXT,
            rag_examples_json   TEXT,
            model_used          TEXT,
            status              TEXT NOT NULL DEFAULT 'pending_review',
            priority_score      REAL,
            original_draft_body TEXT,
            final_sent_body     TEXT,
            edit_distance       REAL,
            rejection_reason    TEXT,
            created_at          TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            approved_at         TEXT,
            sent_at             TEXT,
            expires_at          TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_drafts_status
            ON email_drafts(status, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_drafts_account
            ON email_drafts(account_email, status);
        CREATE INDEX IF NOT EXISTS idx_drafts_thread
            ON email_drafts(thread_id, account_email);
    """)
    conn.commit()

    # ── Directive 015: Model Registry & Dynamic Routing ─────────
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS model_registry (
            id                    INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id          TEXT NOT NULL UNIQUE,
            provider              TEXT NOT NULL,
            provider_model_id     TEXT NOT NULL,
            display_name          TEXT NOT NULL,
            tier                  TEXT NOT NULL DEFAULT 'fast',
            pricing_input_per_mtok  REAL,
            pricing_output_per_mtok REAL,
            copilot_multiplier    REAL,
            context_window        INTEGER DEFAULT 128000,
            max_output_tokens     INTEGER,
            supports_tools        INTEGER DEFAULT 0,
            supports_vision       INTEGER DEFAULT 0,
            supports_streaming    INTEGER DEFAULT 1,
            supports_json_mode    INTEGER DEFAULT 0,
            speed_class           TEXT DEFAULT 'standard',
            is_verified           INTEGER DEFAULT 0,
            is_deprecated         INTEGER DEFAULT 0,
            is_preview            INTEGER DEFAULT 0,
            sunset_date           TEXT,
            successor_model_id    TEXT,
            discovered_at         TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            last_verified_at      TEXT,
            last_used_at          TEXT,
            notes                 TEXT,
            lifecycle_state       TEXT DEFAULT 'general',
            pricing_source        TEXT,
            pricing_source_url    TEXT,
            pricing_effective_at  TEXT,
            pricing_last_checked_at TEXT,
            pricing_stale_after_days INTEGER DEFAULT 30,
            pricing_confidence    REAL DEFAULT 1.0,
            UNIQUE(provider, provider_model_id)
        );
        CREATE INDEX IF NOT EXISTS idx_model_reg_provider
            ON model_registry(provider, is_verified, is_deprecated);
        CREATE INDEX IF NOT EXISTS idx_model_reg_tier
            ON model_registry(tier, is_verified)
            WHERE is_deprecated = 0;
        CREATE INDEX IF NOT EXISTS idx_model_reg_canonical
            ON model_registry(canonical_id);

        CREATE TABLE IF NOT EXISTS model_aliases (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            alias     TEXT NOT NULL UNIQUE,
            canonical_id TEXT NOT NULL REFERENCES model_registry(canonical_id),
            source    TEXT NOT NULL DEFAULT 'manual'
        );
        CREATE INDEX IF NOT EXISTS idx_model_alias_canonical
            ON model_aliases(canonical_id);

        CREATE TABLE IF NOT EXISTS model_quality_scores (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id  TEXT NOT NULL REFERENCES model_registry(canonical_id),
            task_type     TEXT NOT NULL,
            alpha         REAL NOT NULL DEFAULT 3.0,
            beta          REAL NOT NULL DEFAULT 1.0,
            total_calls   INTEGER NOT NULL DEFAULT 0,
            successes     INTEGER NOT NULL DEFAULT 0,
            failures      INTEGER NOT NULL DEFAULT 0,
            avg_cost_usd  REAL DEFAULT 0.0,
            avg_latency_ms REAL DEFAULT 0.0,
            last_updated  TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now')),
            UNIQUE(canonical_id, task_type)
        );
        CREATE INDEX IF NOT EXISTS idx_quality_task
            ON model_quality_scores(task_type, canonical_id);

        CREATE TABLE IF NOT EXISTS model_pricing_history (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            canonical_id  TEXT NOT NULL REFERENCES model_registry(canonical_id),
            field_changed TEXT NOT NULL,
            old_value     REAL,
            new_value     REAL,
            source        TEXT NOT NULL DEFAULT 'discovery',
            changed_at    TEXT NOT NULL DEFAULT (strftime('%Y-%m-%dT%H:%M:%fZ','now'))
        );
        CREATE INDEX IF NOT EXISTS idx_pricing_hist_model
            ON model_pricing_history(canonical_id, changed_at DESC);
    """)
    conn.commit()

    # ── Directive 018: Project Hub — Unified Workspace Command Center ──
    conn.executescript("""
        -- Central project entity — the hub of all work
        CREATE TABLE IF NOT EXISTS projects (
            id              TEXT PRIMARY KEY,
            name            TEXT NOT NULL,
            description     TEXT DEFAULT '',
            slug            TEXT UNIQUE,
            project_type    TEXT NOT NULL DEFAULT 'general'
                CHECK(project_type IN (
                    'code','repair','research','personal',
                    'finance','general','mission'
                )),
            status          TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN (
                    'planning','active','paused','completed',
                    'archived','cancelled'
                )),
            health          TEXT DEFAULT 'on_track'
                CHECK(health IN ('on_track','at_risk','off_track','unknown')),
            priority        INTEGER DEFAULT 0,
            start_date      TEXT,
            target_date     TEXT,
            completed_at    TEXT,
            metadata        TEXT NOT NULL DEFAULT '{}',
            icon            TEXT,
            color           TEXT,
            sort_order      REAL DEFAULT 0,
            parent_project_id TEXT REFERENCES projects(id) ON DELETE SET NULL,
            lead_agent      TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now')),
            archived_at     TEXT,
            last_accessed_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_projects_status
            ON projects(status, updated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_projects_type
            ON projects(project_type, status);
        CREATE INDEX IF NOT EXISTS idx_projects_last_accessed
            ON projects(last_accessed_at DESC)
            WHERE status = 'active';

        -- Episodic memory: raw event log per project
        CREATE TABLE IF NOT EXISTS project_events (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            event_type      TEXT NOT NULL,
            agent_id        TEXT,
            summary         TEXT NOT NULL,
            details         TEXT DEFAULT '{}',
            importance      INTEGER DEFAULT 5
                CHECK(importance BETWEEN 1 AND 10),
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            distilled       INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_proj_events_project
            ON project_events(project_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_proj_events_undistilled
            ON project_events(project_id, distilled)
            WHERE distilled = 0;

        -- Semantic memory: distilled knowledge per project
        CREATE TABLE IF NOT EXISTS project_knowledge (
            id              TEXT PRIMARY KEY,
            project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            knowledge_type  TEXT NOT NULL
                CHECK(knowledge_type IN (
                    'fact','decision','blocker','milestone',
                    'preference','pattern','context','summary'
                )),
            content         TEXT NOT NULL,
            confidence      REAL DEFAULT 1.0,
            source_event_ids TEXT DEFAULT '[]',
            valid_until     TEXT,
            superseded_by   TEXT REFERENCES project_knowledge(id),
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_proj_knowledge_project
            ON project_knowledge(project_id, knowledge_type);

        -- Bridge: project ↔ mission
        CREATE TABLE IF NOT EXISTS project_mission_map (
            project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            mission_id  INTEGER NOT NULL,
            role        TEXT DEFAULT 'primary',
            PRIMARY KEY (project_id, mission_id)
        );

        -- Bridge: project ↔ task
        CREATE TABLE IF NOT EXISTS project_task_map (
            project_id  TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            task_id     INTEGER NOT NULL,
            PRIMARY KEY (project_id, task_id)
        );

        -- Bridge: project ↔ conversation
        CREATE TABLE IF NOT EXISTS project_conversation_map (
            project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            conversation_id INTEGER NOT NULL,
            PRIMARY KEY (project_id, conversation_id)
        );

        -- Agent routing rules (project_type → agent)
        CREATE TABLE IF NOT EXISTS agent_routing_rules (
            id              TEXT PRIMARY KEY,
            project_type    TEXT NOT NULL,
            action_pattern  TEXT,
            agent_id        TEXT NOT NULL,
            priority        INTEGER DEFAULT 0,
            is_active       INTEGER DEFAULT 1,
            conditions      TEXT DEFAULT '{}'
        );
        CREATE INDEX IF NOT EXISTS idx_routing_rules_type
            ON agent_routing_rules(project_type, is_active, priority DESC);

        -- Repo registry: maps projects to local repo paths
        CREATE TABLE IF NOT EXISTS repo_registry (
            id              TEXT PRIMARY KEY,
            project_id      TEXT REFERENCES projects(id) ON DELETE SET NULL,
            name            TEXT NOT NULL,
            local_path      TEXT NOT NULL UNIQUE,
            default_branch  TEXT DEFAULT 'main',
            language        TEXT,
            build_command   TEXT,
            test_command    TEXT,
            lint_command    TEXT,
            repo_map_cache  TEXT,
            repo_map_updated_at TEXT,
            last_indexed_at TEXT,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_repo_registry_project
            ON repo_registry(project_id);

        -- Source watchers: auto-discovery of new repos/workspaces
        CREATE TABLE IF NOT EXISTS source_watchers (
            id              TEXT PRIMARY KEY,
            name            TEXT,
            watcher_type    TEXT NOT NULL
                CHECK(watcher_type IN (
                    'vscode_workspace','github_user','local_directory'
                )),
            config          TEXT NOT NULL DEFAULT '{}',
            is_active       INTEGER DEFAULT 1,
            last_scan_at    TEXT,
            scan_interval_seconds INTEGER DEFAULT 3600
        );

        -- Discovered sources pending user acceptance
        CREATE TABLE IF NOT EXISTS discovered_sources (
            id              TEXT PRIMARY KEY,
            watcher_id      TEXT REFERENCES source_watchers(id),
            name            TEXT,
            local_path      TEXT,
            source_type     TEXT NOT NULL,
            source_uri      TEXT NOT NULL DEFAULT '',
            suggested_name  TEXT,
            suggested_type  TEXT,
            detected_type   TEXT,
            status          TEXT DEFAULT 'pending'
                CHECK(status IN ('pending','discovered','accepted',
                                 'rejected','dismissed','merged')),
            accepted_project_id TEXT REFERENCES projects(id),
            linked_project_id TEXT REFERENCES projects(id),
            discovered_at   TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_discovered_status
            ON discovered_sources(status);

        -- Coding sessions: iterative agent coding loops
        CREATE TABLE IF NOT EXISTS coding_sessions (
            id              TEXT PRIMARY KEY,
            project_id      TEXT REFERENCES projects(id) ON DELETE SET NULL,
            repo_path       TEXT,
            goal            TEXT NOT NULL,
            agent_id        TEXT,
            model_tier      TEXT DEFAULT 'haiku',
            status          TEXT NOT NULL DEFAULT 'active'
                CHECK(status IN (
                    'active','paused','awaiting_approval',
                    'completed','failed','cancelled'
                )),
            summary         TEXT,
            plan            TEXT DEFAULT '[]',
            turn_count      INTEGER DEFAULT 0,
            max_turns       INTEGER DEFAULT 50,
            max_cost        REAL DEFAULT 0.50,
            total_cost      REAL DEFAULT 0.0,
            total_input_tokens  INTEGER DEFAULT 0,
            total_output_tokens INTEGER DEFAULT 0,
            files_changed   TEXT DEFAULT '[]',
            git_branch      TEXT,
            conversation_history TEXT,
            started_at      TEXT DEFAULT (datetime('now')),
            completed_at    TEXT,
            created_by      TEXT DEFAULT 'owner'
        );
        CREATE INDEX IF NOT EXISTS idx_coding_sessions_project
            ON coding_sessions(project_id, status);
        CREATE INDEX IF NOT EXISTS idx_coding_sessions_active
            ON coding_sessions(status)
            WHERE status IN ('active','paused','awaiting_approval');

        -- Coding session turns: individual LLM round-trips
        CREATE TABLE IF NOT EXISTS coding_session_turns (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES coding_sessions(id) ON DELETE CASCADE,
            turn_number     INTEGER NOT NULL,
            role            TEXT NOT NULL
                CHECK(role IN ('user','assistant','tool_result','system')),
            content         TEXT,
            tool_calls      TEXT,
            model_used      TEXT,
            input_tokens    INTEGER DEFAULT 0,
            output_tokens   INTEGER DEFAULT 0,
            cost            REAL DEFAULT 0.0,
            created_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_coding_turns_session
            ON coding_session_turns(session_id, turn_number);

        -- Command approval log for coding sessions
        CREATE TABLE IF NOT EXISTS coding_approvals (
            id              TEXT PRIMARY KEY,
            session_id      TEXT NOT NULL REFERENCES coding_sessions(id) ON DELETE CASCADE,
            command         TEXT NOT NULL,
            risk_level      TEXT NOT NULL DEFAULT 'medium'
                CHECK(risk_level IN ('low','medium','high','critical')),
            status          TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','approved','rejected','auto_approved')),
            context         TEXT DEFAULT '{}',
            created_at      TEXT DEFAULT (datetime('now')),
            resolved_at     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_coding_approvals_pending
            ON coding_approvals(session_id, status)
            WHERE status = 'pending';

        -- Project chat messages (project-scoped conversation history)
        CREATE TABLE IF NOT EXISTS project_chat_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            role            TEXT NOT NULL CHECK(role IN ('user','assistant','system','tool_result')),
            content         TEXT NOT NULL,
            agent_id        TEXT,
            metadata_json   TEXT DEFAULT '{}',
            actions_json    TEXT DEFAULT '[]',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_proj_chat_project
            ON project_chat_messages(project_id, created_at DESC);

        -- Agent questions awaiting owner input
        CREATE TABLE IF NOT EXISTS agent_questions (
            id              TEXT PRIMARY KEY,
            project_id      TEXT REFERENCES projects(id) ON DELETE CASCADE,
            agent_id        TEXT NOT NULL,
            question        TEXT NOT NULL,
            context         TEXT DEFAULT '{}',
            status          TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','answered','dismissed','expired')),
            answer          TEXT,
            created_at      TEXT DEFAULT (datetime('now')),
            answered_at     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_agent_questions_pending
            ON agent_questions(project_id, status)
            WHERE status = 'pending';

        -- ═══════════════════════════════════════════════════════════
        -- D019: Cognitive Architecture Tables
        -- ═══════════════════════════════════════════════════════════

        -- Phase 1: Evolution proposal dedup + verification
        CREATE TABLE IF NOT EXISTS proposal_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_hash   TEXT NOT NULL,
            description     TEXT NOT NULL,
            target_files    TEXT DEFAULT '[]',
            embedding_json  TEXT,
            times_proposed  INTEGER NOT NULL DEFAULT 1,
            times_applied   INTEGER NOT NULL DEFAULT 0,
            times_rejected  INTEGER NOT NULL DEFAULT 0,
            last_rejection_reason TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            last_proposed_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_proposal_hash
            ON proposal_history(proposal_hash);

        CREATE TABLE IF NOT EXISTS evolution_verification (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            proposal_id     INTEGER REFERENCES proposal_history(id),
            evolution_log_id INTEGER REFERENCES evolution_log(id),
            target_metric   TEXT NOT NULL,
            baseline_value  REAL NOT NULL,
            target_value    REAL,
            post_value      REAL,
            measurement_ticks INTEGER NOT NULL DEFAULT 0,
            status          TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN ('pending','measuring','passed','failed','rolled_back')),
            rollback_reason TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            completed_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_evo_verify_status
            ON evolution_verification(status);

        CREATE TABLE IF NOT EXISTS task_outcome_signals (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            action_name     TEXT NOT NULL,
            task_id         TEXT,
            goal_id         TEXT,
            outcome         TEXT NOT NULL CHECK(outcome IN ('success','failure','partial','reopened','rejected')),
            score_delta     REAL DEFAULT 0.0,
            details_json    TEXT DEFAULT '{}',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_outcome_agent
            ON task_outcome_signals(agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_outcome_action
            ON task_outcome_signals(action_name, outcome);

        -- Phase 2: Cognitive router + reflections
        CREATE TABLE IF NOT EXISTS agent_reflections (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            task_type       TEXT,
            reflection      TEXT NOT NULL,
            lessons_json    TEXT DEFAULT '[]',
            confidence      REAL,
            embedding_json  TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_reflections_agent
            ON agent_reflections(agent_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS cognitive_decisions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            system_used     INTEGER NOT NULL CHECK(system_used IN (1, 2)),
            initial_confidence REAL,
            final_confidence   REAL,
            retries         INTEGER NOT NULL DEFAULT 0,
            escalated       INTEGER NOT NULL DEFAULT 0,
            task_type       TEXT,
            outcome         TEXT,
            cost_usd        REAL DEFAULT 0.0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_cognitive_agent
            ON cognitive_decisions(agent_id, created_at DESC);

        -- Phase 3: Procedural memory (PRAXIS)
        CREATE TABLE IF NOT EXISTS procedural_experiences (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            env_state_json  TEXT NOT NULL,
            internal_state_json TEXT NOT NULL,
            action_taken    TEXT NOT NULL,
            action_params_json TEXT DEFAULT '{}',
            outcome         TEXT NOT NULL,
            reward          REAL NOT NULL DEFAULT 0.0,
            state_embedding_json TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_procedural_agent
            ON procedural_experiences(agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_procedural_outcome
            ON procedural_experiences(outcome, reward);

        -- Phase 4: Behavioral rules (AutoManual)
        CREATE TABLE IF NOT EXISTS agent_rules (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL DEFAULT '*',
            rule_type       TEXT NOT NULL CHECK(rule_type IN ('skill','constraint','preference')),
            condition_text  TEXT NOT NULL,
            action_text     TEXT NOT NULL,
            confidence      REAL NOT NULL DEFAULT 0.5,
            times_applied   INTEGER NOT NULL DEFAULT 0,
            times_succeeded INTEGER NOT NULL DEFAULT 0,
            times_failed    INTEGER NOT NULL DEFAULT 0,
            source          TEXT DEFAULT 'extracted',
            active          INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            last_applied_at TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_rules_agent_active
            ON agent_rules(agent_id, active)
            WHERE active = 1;
        CREATE INDEX IF NOT EXISTS idx_rules_type
            ON agent_rules(rule_type, confidence DESC);

        CREATE TABLE IF NOT EXISTS rule_applications (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            rule_id         INTEGER NOT NULL REFERENCES agent_rules(id),
            agent_id        TEXT NOT NULL,
            context_summary TEXT,
            outcome         TEXT NOT NULL CHECK(outcome IN ('success','failure','neutral')),
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_rule_app_rule
            ON rule_applications(rule_id, outcome);

        -- Phase 5: Proactive awareness
        CREATE TABLE IF NOT EXISTS proactive_events (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source          TEXT NOT NULL,
            event_type      TEXT NOT NULL,
            summary         TEXT NOT NULL,
            details_json    TEXT DEFAULT '{}',
            priority_score  REAL DEFAULT 0.0,
            processed       INTEGER NOT NULL DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_proactive_unprocessed
            ON proactive_events(processed, created_at)
            WHERE processed = 0;

        CREATE TABLE IF NOT EXISTS proactive_insights (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            insight_text    TEXT NOT NULL,
            source_event_ids TEXT DEFAULT '[]',
            priority_score  REAL NOT NULL DEFAULT 0.0,
            channel         TEXT DEFAULT 'feed'
                CHECK(channel IN ('feed','chat','sms','push')),
            delivered       INTEGER NOT NULL DEFAULT 0,
            acted_on        INTEGER,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            delivered_at    TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_insights_undelivered
            ON proactive_insights(delivered, priority_score DESC)
            WHERE delivered = 0;

        -- Phase 6: Temporal knowledge graph
        CREATE TABLE IF NOT EXISTS kg_nodes (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            entity_type     TEXT NOT NULL,
            name            TEXT NOT NULL,
            summary         TEXT,
            properties_json TEXT DEFAULT '{}',
            embedding_json  TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_kg_nodes_unique
            ON kg_nodes(entity_type, name);
        CREATE INDEX IF NOT EXISTS idx_kg_nodes_type
            ON kg_nodes(entity_type);

        CREATE TABLE IF NOT EXISTS kg_edges (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            source_id       INTEGER NOT NULL REFERENCES kg_nodes(id),
            target_id       INTEGER NOT NULL REFERENCES kg_nodes(id),
            relation        TEXT NOT NULL,
            weight          REAL NOT NULL DEFAULT 1.0,
            properties_json TEXT DEFAULT '{}',
            valid_from      TEXT NOT NULL DEFAULT (datetime('now')),
            valid_to        TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_kg_edges_source
            ON kg_edges(source_id, valid_to)
            WHERE valid_to IS NULL;
        CREATE INDEX IF NOT EXISTS idx_kg_edges_target
            ON kg_edges(target_id, valid_to)
            WHERE valid_to IS NULL;
        CREATE INDEX IF NOT EXISTS idx_kg_edges_relation
            ON kg_edges(relation);

        -- Phase 7: Project context isolation
        CREATE TABLE IF NOT EXISTS project_contexts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id      TEXT NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
            block_type      TEXT NOT NULL CHECK(block_type IN ('system','core','status','briefing','custom')),
            block_name      TEXT NOT NULL,
            content         TEXT NOT NULL,
            token_count     INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_proj_ctx_block
            ON project_contexts(project_id, block_type, block_name);
    """)
    conn.commit()

    # FTS5 for project knowledge search
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS project_knowledge_fts
            USING fts5(
                content,
                content='project_knowledge',
                content_rowid=rowid,
                tokenize='porter unicode61'
            )
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS proj_knowledge_fts_insert
            AFTER INSERT ON project_knowledge BEGIN
                INSERT INTO project_knowledge_fts(rowid, content)
                VALUES (new.rowid, new.content);
            END
            """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS proj_knowledge_fts_delete
            AFTER DELETE ON project_knowledge BEGIN
                INSERT INTO project_knowledge_fts(project_knowledge_fts, rowid, content)
                VALUES ('delete', old.rowid, old.content);
            END
            """)
        conn.commit()
    except Exception:
        pass  # FTS5 already exists

    # Phase 2.2: sqlite-vec virtual table (cannot be inside executescript)
    _init_vector_tables(conn)

    # ── Directive 019: Creativity & Mashgiach departments ──────────
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS creativity_proposals (
            id              TEXT PRIMARY KEY,
            title           TEXT NOT NULL,
            domain          TEXT NOT NULL DEFAULT 'general',
            description     TEXT NOT NULL,
            status          TEXT NOT NULL DEFAULT 'proposed'
                CHECK(status IN ('proposed','evaluated','accepted','rejected','implemented')),
            priority        INTEGER NOT NULL DEFAULT 5,
            evaluation_notes TEXT DEFAULT '',
            impact_estimate TEXT DEFAULT '',
            created_by      TEXT NOT NULL DEFAULT 'dept_creativity',
            resolved_by     TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            resolved_at     TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_creativity_proposals_status
            ON creativity_proposals(status, priority DESC);
        CREATE INDEX IF NOT EXISTS idx_creativity_proposals_domain
            ON creativity_proposals(domain, created_at DESC);

        CREATE TABLE IF NOT EXISTS mashgiach_audit_log (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            agent_id        TEXT NOT NULL,
            department      TEXT,
            finding_type    TEXT NOT NULL,
            severity        TEXT NOT NULL DEFAULT 'info'
                CHECK(severity IN ('info','warning','critical')),
            auto_fixed      INTEGER NOT NULL DEFAULT 0,
            finding_text    TEXT NOT NULL,
            correction_text TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_mashgiach_log_agent
            ON mashgiach_audit_log(agent_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mashgiach_log_severity
            ON mashgiach_audit_log(severity, auto_fixed, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_mashgiach_log_dept
            ON mashgiach_audit_log(department, created_at DESC);

        CREATE TABLE IF NOT EXISTS mashgiach_dept_scores (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            department      TEXT NOT NULL,
            week_start      TEXT NOT NULL,
            autonomy_score  REAL NOT NULL DEFAULT 3.0,
            quality_score   REAL NOT NULL DEFAULT 3.0,
            initiative_score REAL NOT NULL DEFAULT 3.0,
            accuracy_score  REAL NOT NULL DEFAULT 3.0,
            standing_orders_pct REAL DEFAULT NULL,
            findings_count  INTEGER NOT NULL DEFAULT 0,
            auto_fixes      INTEGER NOT NULL DEFAULT 0,
            escalations     INTEGER NOT NULL DEFAULT 0,
            notes           TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(department, week_start)
        );
        CREATE INDEX IF NOT EXISTS idx_mashgiach_scores_dept
            ON mashgiach_dept_scores(department, week_start DESC);

        -- ── Watch party: video library ──────────────────────────
        CREATE TABLE IF NOT EXISTS watch_videos (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            title           TEXT NOT NULL,
            description     TEXT DEFAULT '',
            cloudflare_uid  TEXT NOT NULL,
            duration_secs   REAL DEFAULT 0,
            thumbnail_url   TEXT DEFAULT '',
            uploaded_by     TEXT NOT NULL DEFAULT 'eli',
            file_name       TEXT DEFAULT '',
            mime_type       TEXT DEFAULT 'video/mp4',
            file_size_bytes INTEGER DEFAULT 0,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_videos_created
            ON watch_videos(created_at DESC);

        -- ── Watch party: watch history per user ──────────────────
        CREATE TABLE IF NOT EXISTS watch_history (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id        INTEGER NOT NULL REFERENCES watch_videos(id),
            username        TEXT NOT NULL,
            last_pos_secs   REAL DEFAULT 0,
            completed       INTEGER NOT NULL DEFAULT 0,
            watched_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_history_user
            ON watch_history(username, video_id);
        CREATE INDEX IF NOT EXISTS idx_watch_history_video
            ON watch_history(video_id);

        -- ── Watch party: rooms (watch sessions) ─────────────────
        CREATE TABLE IF NOT EXISTS watch_rooms (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            room_code       TEXT NOT NULL UNIQUE,
            video_id        INTEGER NOT NULL REFERENCES watch_videos(id),
            created_by      TEXT NOT NULL,
            is_active       INTEGER NOT NULL DEFAULT 1,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_rooms_code
            ON watch_rooms(room_code);

        -- ── Watch party: bookmarks (timestamp snapshots) ─────────
        CREATE TABLE IF NOT EXISTS watch_bookmarks (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id        INTEGER NOT NULL REFERENCES watch_videos(id),
            username        TEXT NOT NULL,
            timestamp_secs  REAL NOT NULL,
            label           TEXT DEFAULT '',
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_bookmarks_video
            ON watch_bookmarks(video_id, username);

        -- ── Watch party: timestamp comments on videos ────────────
        CREATE TABLE IF NOT EXISTS watch_comments (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id        INTEGER NOT NULL REFERENCES watch_videos(id),
            username        TEXT NOT NULL,
            timestamp_secs  REAL DEFAULT NULL,
            message         TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_comments_video
            ON watch_comments(video_id);

        -- ── Watch party: room chat messages ──────────────────────
        CREATE TABLE IF NOT EXISTS watch_chat_messages (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            room_id         INTEGER NOT NULL REFERENCES watch_rooms(id),
            username        TEXT NOT NULL,
            message         TEXT NOT NULL,
            created_at      TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_watch_chat_room
            ON watch_chat_messages(room_id);
    """)
    conn.commit()

    _normalize_assignment_alias_rows(conn)
    conn.commit()

    # Phase 3.4: Owner model tables (knowledge graph)
    try:
        from app.services.owner_model import init_owner_model_tables

        init_owner_model_tables(db_url)
        _log.info("Owner model tables ready")
    except Exception as exc:
        _log.warning("Owner model table init failed (non-fatal): %s", exc)


def _init_vector_tables(conn: sqlite3.Connection) -> None:
    """Load sqlite-vec extension and create vector + FTS5 tables.

    This runs as a separate step because ``executescript`` does not
    support loading extensions or virtual table creation via ``vec0``.
    Gracefully skips when ``sqlite-vec`` is not installed.
    """
    # ── sqlite-vec: vector search ──────────────────────────────────
    try:
        if not _ensure_sqlite_vec_loaded(conn):
            raise RuntimeError("sqlite-vec unavailable")
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memory_vectors USING vec0(
                memory_id INTEGER PRIMARY KEY,
                agent_id  TEXT partition key,
                embedding float[1536] distance_metric=cosine
            )
        """)
        conn.commit()
        _log.info("sqlite-vec: memory_vectors virtual table ready")
    except RuntimeError as exc:
        if str(exc) != "sqlite-vec unavailable":
            _log.warning("sqlite-vec init failed (non-fatal): %s", exc)
    except Exception as exc:
        _log.warning("sqlite-vec init failed (non-fatal): %s", exc)

    # ── FTS5: keyword search ───────────────────────────────────────
    try:
        conn.execute("""
            CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                content,
                content='memories',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """)
        # Triggers to keep FTS5 synchronised with memories table
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_fts_insert
            AFTER INSERT ON memories BEGIN
                INSERT INTO memories_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_fts_delete
            AFTER DELETE ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
            END
        """)
        conn.execute("""
            CREATE TRIGGER IF NOT EXISTS memories_fts_update
            AFTER UPDATE OF content ON memories BEGIN
                INSERT INTO memories_fts(memories_fts, rowid, content)
                VALUES ('delete', old.id, old.content);
                INSERT INTO memories_fts(rowid, content)
                VALUES (new.id, new.content);
            END
        """)
        conn.commit()
        _log.info("FTS5: memories_fts virtual table + triggers ready")
    except Exception as exc:
        # 2026-08-31: recover from orphaned FTS5 shadow tables. If the
        # virtual table row was dropped (migration/partial restore) but
        # memories_fts_data/_idx/_docsize/_config survived, CREATE VIRTUAL
        # TABLE fails with "table 'memories_fts_data' already exists" and
        # EVERY subsequent INSERT INTO memories dies via the trigger
        # ("no such table: main.memories_fts") — silent total memory loss
        # (production memories table stopped receiving rows 2026-07-05).
        # Repair: drop the orphaned shadow tables, recreate the FTS table,
        # and rebuild the index from the memories table.
        _log.warning("FTS5 init failed (non-fatal): %s", exc)
        try:
            shadow = [
                r[0]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master "
                    "WHERE type='table' AND name LIKE 'memories_fts_%' "
                    "AND name NOT LIKE '%_insert' AND name NOT LIKE '%_delete' "
                    "AND name NOT LIKE '%_update'"
                ).fetchall()
            ]
            if "memories_fts_data" in shadow:
                _log.warning(
                    "FTS5: orphaned shadow tables detected (%d) — dropping "
                    "to recover memories_fts",
                    len(shadow),
                )
                for tbl in shadow:
                    try:
                        conn.execute(f'DROP TABLE IF EXISTS "{tbl}"')
                    except Exception as drop_exc:
                        _log.warning(
                            "FTS5: failed to drop orphan %s: %s",
                            tbl,
                            drop_exc,
                        )
                conn.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        content,
                        content='memories',
                        content_rowid='id',
                        tokenize='porter unicode61'
                    )
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_insert
                    AFTER INSERT ON memories BEGIN
                        INSERT INTO memories_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_delete
                    AFTER DELETE ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                    END
                """)
                conn.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_update
                    AFTER UPDATE OF content ON memories BEGIN
                        INSERT INTO memories_fts(memories_fts, rowid, content)
                        VALUES ('delete', old.id, old.content);
                        INSERT INTO memories_fts(rowid, content)
                        VALUES (new.id, new.content);
                    END
                """)
                try:
                    conn.execute(
                        "INSERT INTO memories_fts(memories_fts) VALUES('rebuild')"
                    )
                    _log.info("FTS5: memories_fts rebuilt from %s memories", 
                              conn.execute(
                                  "SELECT count(*) FROM memories"
                              ).fetchone()[0])
                except Exception as rebuild_exc:
                    _log.warning("FTS5: rebuild failed (non-fatal): %s", rebuild_exc)
                conn.commit()
        except Exception as repair_exc:
            _log.warning("FTS5: repair failed (non-fatal): %s", repair_exc)


# ---------------------------------------------------------------------------
# sqlite-vec vector operations (Phase 2.2)
# ---------------------------------------------------------------------------


def _serialize_embedding(embedding: list[float]) -> bytes:
    """Serialize a float list to binary for sqlite-vec."""
    import struct

    return struct.pack(f"{len(embedding)}f", *embedding)


def store_memory_entry(
    db_url: str,
    *,
    content: str,
    category: str = "general",
    agent_id: str = "orchestrator",
    source: str = "manual",
    importance: int = 5,
    tags: list[str] | None = None,
    embedding: list[float] | None = None,
) -> int:
    """Insert a memory entry (and optional vector) into SQLite.

    Returns the new row ID.
    """
    import json as _json

    now = _now_iso()
    tags_json = _json.dumps(tags or [])
    conn = _get_conn(db_url)
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO memory_entries "
            "(content, category, agent_id, source, importance, tags, "
            " created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (content, category, agent_id, source, importance, tags_json, now, now),
        )
        row_id = cur.lastrowid

        if embedding and row_id:
            try:
                if _ensure_sqlite_vec_loaded(conn):
                    conn.execute(
                        "INSERT INTO memory_vectors (memory_id, embedding) "
                        "VALUES (?, ?)",
                        (row_id, _serialize_embedding(embedding)),
                    )
            except Exception as exc:
                _log.warning(
                    "Failed to store embedding for entry %d: %s",
                    row_id,
                    exc,
                )
        conn.commit()
    return row_id  # type: ignore[return-value]


def vector_search_memories(
    db_url: str,
    query_embedding: list[float],
    *,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """KNN vector search in SQLite via sqlite-vec.

    Returns a list of dicts with keys:
    ``id, content, category, agent_id, distance``.
    """
    conn = _get_conn(db_url)
    if not _ensure_sqlite_vec_loaded(conn):
        return []

    with _db_lock:
        rows = conn.execute(
            """
            SELECT m.id, m.content, m.category, m.agent_id,
                   m.source, m.importance, m.created_at,
                   v.distance
            FROM memory_vectors v
            JOIN memory_entries m ON m.id = v.memory_id
            WHERE v.embedding MATCH ?
            ORDER BY v.distance
            LIMIT ?
            """,
            (_serialize_embedding(query_embedding), limit),
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Model usage tracking (cost optimization)
# ---------------------------------------------------------------------------


def log_model_usage(
    db_url: str,
    *,
    agent_id: str = "orchestrator",
    provider: str,
    model: str,
    tier: str = "ceo",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    cached_tokens: int = 0,
    prompt_prefix_hash: str | None = None,
    served_by: str | None = None,
    session_id: str | None = None,
    estimated_cost_usd: float = 0.0,
    latency_ms: int = 0,
    success: bool = True,
    error_message: str | None = None,
) -> int:
    """Record a single LLM call for cost/performance tracking."""

    # ── CALLER-STACK diagnostic (2026-10-20) ──
    # One writer serves every caller, so naming the caller here is the only way to tell which
    # code path spends the money. Inert unless AGENT_LOG_CALLER_STACK is set. No content, no secrets.
    try:
        import os as _cs_os

        if _cs_os.environ.get("AGENT_LOG_CALLER_STACK", "").strip().lower() in ("1", "true", "yes", "on"):
            import traceback as _cs_tb

            _cs_frames = [
                f for f in _cs_tb.extract_stack()
                if "/app/" in f.filename.replace("\\", "/") and "database.py" not in f.filename
            ]
            _cs_path = " <- ".join(
                "%s:%d:%s" % (f.filename.rsplit("/", 1)[-1], f.lineno, f.name)
                for f in _cs_frames[-3:]
            )
            print(
                "USAGE-CALLER agent=%s model=%s provider=%s in=%d path=%s"
                % (agent_id, model, provider, prompt_tokens, _cs_path),
                flush=True,
            )
    except Exception:
        pass
    now = _now_iso()
    conn = _get_conn(db_url)
    with _db_lock:
        cur = conn.execute(
            """
            INSERT INTO model_usage (
                agent_id,
                provider, model, tier,
                prompt_tokens, completion_tokens, total_tokens,
                cached_tokens, prompt_prefix_hash, served_by, session_id,
                estimated_cost_usd, latency_ms,
                success, error_message, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                agent_id,
                provider,
                model,
                tier,
                prompt_tokens,
                completion_tokens,
                total_tokens,
                cached_tokens,
                prompt_prefix_hash,
                served_by,
                session_id,
                estimated_cost_usd,
                latency_ms,
                1 if success else 0,
                error_message,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_model_usage_stats_by_agent(
    db_url: str,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get aggregated usage stats per agent for the last N days.

    Each row includes a ``traffic_class`` field: ``'gateway'`` for
    VS Code Copilot gateway traffic (agent_id in _GATEWAY_AGENT_IDS),
    ``'company'`` for all autonomous company agents.
    """
    conn = _get_conn(db_url)
    placeholders = ",".join("?" * len(_GATEWAY_AGENT_IDS))
    with _db_lock:
        rows = conn.execute(
            f"""
            SELECT
                COALESCE(agent_id, 'orchestrator') as agent_id,
                CASE WHEN agent_id IN ({placeholders}) THEN 'gateway'
                     ELSE 'company' END as traffic_class,
                COUNT(*) as call_count,
                COALESCE(SUM(total_tokens), 0) as total_tokens,
                ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) as total_cost_usd,
                ROUND(AVG(latency_ms), 0) as avg_latency_ms,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END)
                    as success_count,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)
                    as failure_count
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            GROUP BY COALESCE(agent_id, 'orchestrator')
            ORDER BY total_cost_usd DESC
            """,
            (*_GATEWAY_AGENT_IDS, f"-{days} days"),
        ).fetchall()
    return [dict(row) for row in rows]


def get_gateway_daily_llm_spend(db_url: str) -> float:
    """Return today's total estimated LLM cost for gateway traffic only."""
    conn = _get_conn(db_url)
    placeholders = ",".join("?" * len(_GATEWAY_AGENT_IDS))
    with _db_lock:
        row = conn.execute(
            f"""
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total
            FROM model_usage
            WHERE date(created_at) = date('now')
              AND agent_id IN ({placeholders})
            """,
            _GATEWAY_AGENT_IDS,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_model_usage_cost_total(
    db_url: str,
    *,
    days: int = 30,
) -> float:
    """Return total estimated cost in the last N days."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT
                ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) as total_cost_usd
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            """,
            (f"-{days} days",),
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total_cost_usd"])
    except Exception:
        return 0.0


def get_model_usage_stats(
    db_url: str,
    *,
    days: int = 30,
) -> list[dict]:
    """Get aggregated usage stats per provider/model for the
    last N days."""
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """
            SELECT
                provider, model, tier,
                COUNT(*) as call_count,
                SUM(total_tokens) as total_tokens,
                ROUND(SUM(estimated_cost_usd), 6) as total_cost_usd,
                ROUND(AVG(latency_ms), 0) as avg_latency_ms,
                SUM(CASE WHEN success = 1 THEN 1 ELSE 0 END)
                    as success_count,
                SUM(CASE WHEN success = 0 THEN 1 ELSE 0 END)
                    as failure_count
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            GROUP BY provider, model, tier
            ORDER BY total_cost_usd DESC
            """,
            (f"-{days} days",),
        ).fetchall()
        return [dict(row) for row in rows]


def get_model_usage_daily_totals(
    db_url: str,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get daily total cost/tokens/calls for the last N days."""
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """
            SELECT
                date(created_at) AS day,
                COUNT(*) AS call_count,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total_cost_usd
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            GROUP BY date(created_at)
            ORDER BY day ASC
            """,
            (f"-{days} days",),
        ).fetchall()
    return [dict(row) for row in rows]


def get_model_usage_daily_breakdown(
    db_url: str,
    *,
    days: int = 30,
) -> list[dict[str, Any]]:
    """Get daily cost totals broken down by provider/model for last N days.

    Returns rows like:
      {day, provider, model, tier, total_cost_usd, call_count, total_tokens}
    """
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """
            SELECT
                date(created_at) AS day,
                provider,
                model,
                tier,
                COUNT(*) AS call_count,
                COALESCE(SUM(total_tokens), 0) AS total_tokens,
                ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total_cost_usd
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            GROUP BY date(created_at), provider, model, tier
            ORDER BY day ASC, total_cost_usd DESC
            """,
            (f"-{days} days",),
        ).fetchall()
    return [dict(row) for row in rows]


def get_daily_llm_spend(db_url: str) -> float:
    """Return today's total estimated LLM cost in USD."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE date(created_at) = date('now')
            """,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_monthly_llm_spend(db_url: str) -> float:
    """Return this calendar month's total estimated LLM cost in USD."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE strftime('%Y-%m', created_at)
                = strftime('%Y-%m', 'now')
            """,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_agent_monthly_spend(db_url: str, agent_id: str) -> float:
    """Return this calendar month's total estimated LLM cost for a specific agent."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE agent_id = ?
              AND strftime('%Y-%m', created_at)
                = strftime('%Y-%m', 'now')
            """,
            (agent_id,),
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_agent_daily_spend(db_url: str, agent_id: str) -> float:
    """Return today's total estimated LLM cost for a specific agent."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE agent_id = ?
              AND date(created_at) = date('now')
            """,
            (agent_id,),
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_rolling_24h_llm_spend(db_url: str) -> float:
    """Return total estimated LLM cost in the last 24 hours (rolling window)."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')
            """,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


# ── Gateway-excluded (company-only) spend helpers ─────────────────────────────
# These exclude the 'vscode_gateway' agent so company-agent budget checks
# don't count VS Code Copilot traffic, and vice versa.

_GATEWAY_AGENT_IDS = ("vscode_gateway",)


def get_company_daily_llm_spend(db_url: str) -> float:
    """Return today's total estimated LLM cost excluding gateway traffic."""
    conn = _get_conn(db_url)
    placeholders = ",".join("?" * len(_GATEWAY_AGENT_IDS))
    with _db_lock:
        row = conn.execute(
            f"""
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total
            FROM model_usage
            WHERE date(created_at) = date('now')
              AND agent_id NOT IN ({placeholders})
            """,
            _GATEWAY_AGENT_IDS,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_company_rolling_24h_llm_spend(db_url: str) -> float:
    """Return rolling 24h estimated LLM cost excluding gateway traffic."""
    conn = _get_conn(db_url)
    placeholders = ",".join("?" * len(_GATEWAY_AGENT_IDS))
    with _db_lock:
        row = conn.execute(
            f"""
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total
            FROM model_usage
            WHERE created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')
              AND agent_id NOT IN ({placeholders})
            """,
            _GATEWAY_AGENT_IDS,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_agent_rolling_24h_spend(db_url: str, agent_id: str) -> float:
    """Return per-agent estimated LLM cost in the last 24 hours."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6)
                AS total
            FROM model_usage
            WHERE agent_id = ?
              AND created_at >= strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')
            """,
            (agent_id,),
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_agent_velocity_spend(db_url: str, agent_id: str, minutes: int = 5) -> float:
    """Return agent spend in the last N minutes (velocity check)."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(estimated_cost_usd), 0.0) AS total
            FROM model_usage
            WHERE agent_id = ?
              AND created_at > strftime('%Y-%m-%dT%H:%M:%S', 'now', ?)
            """,
            (agent_id, f"-{minutes} minutes"),
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_gateway_daily_llm_spend(db_url: str) -> float:
    """Return today's estimated LLM cost for gateway / VS Code traffic only."""
    conn = _get_conn(db_url)
    placeholders = ",".join("?" * len(_GATEWAY_AGENT_IDS))
    with _db_lock:
        row = conn.execute(
            f"""
            SELECT ROUND(COALESCE(SUM(estimated_cost_usd), 0.0), 6) AS total
            FROM model_usage
            WHERE date(created_at) = date('now')
              AND agent_id IN ({placeholders})
            """,
            _GATEWAY_AGENT_IDS,
        ).fetchone()
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_research_daily_spend(db_url: str) -> float:
    """Return today's realized research-job cost in USD (0 if table absent)."""
    conn = _get_conn(db_url)
    with _db_lock:
        try:
            row = conn.execute(
                """
                SELECT ROUND(COALESCE(SUM(cost_usd), 0.0), 6) AS total
                FROM research_jobs
                WHERE date(COALESCE(completed_at, submitted_at)) = date('now')
                """,
            ).fetchone()
        except Exception:
            return 0.0
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


def get_research_monthly_spend(db_url: str) -> float:
    """Return this calendar month's realized research-job cost (0 if absent)."""
    conn = _get_conn(db_url)
    with _db_lock:
        try:
            row = conn.execute(
                """
                SELECT ROUND(COALESCE(SUM(cost_usd), 0.0), 6) AS total
                FROM research_jobs
                WHERE strftime('%Y-%m', COALESCE(completed_at, submitted_at))
                    = strftime('%Y-%m', 'now')
                """,
            ).fetchone()
        except Exception:
            return 0.0
    if not row:
        return 0.0
    try:
        return float(row["total"])
    except Exception:
        return 0.0


# ── Deferred LLM work queue (tiered enforcement wait-and-resume) ──────────────
# Durable park-and-resume store for work paused under budget pressure. Modeled
# on outbound_buffer's backoff pattern. See app/services/deferred_work.py.


def enqueue_deferred_work(
    db_url: str,
    *,
    work_type: str,
    priority: str,
    payload: dict[str, Any] | None = None,
    pool: str = "company",
    reason: str = "",
    next_attempt_at: str | None = None,
    dedup_key: str | None = None,
    max_attempts: int = 5,
) -> int | None:
    """Park a unit of work for later resumption. Returns row id (or existing id
    when a pending row with the same dedup_key already exists)."""
    conn = _get_conn(db_url)
    # Ensure the deferred_llm_work table exists (safe for test/dynamic DBs)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS deferred_llm_work (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            work_type       TEXT NOT NULL,
            priority        TEXT NOT NULL DEFAULT 'P2',
            pool            TEXT NOT NULL DEFAULT 'company',
            payload         TEXT NOT NULL DEFAULT '{}',
            reason          TEXT,
            status          TEXT NOT NULL DEFAULT 'pending',
            attempts        INTEGER NOT NULL DEFAULT 0,
            max_attempts    INTEGER NOT NULL DEFAULT 5,
            next_attempt_at TEXT NOT NULL,
            dedup_key       TEXT,
            created_at      TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at      TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_deferred_work_due
            ON deferred_llm_work(status, next_attempt_at)
    """)
    conn.execute("""
        CREATE INDEX IF NOT EXISTS idx_deferred_work_dedup
            ON deferred_llm_work(dedup_key, status)
    """)
    now = _now_iso()
    next_at = next_attempt_at or now
    with _db_lock:
        if dedup_key:
            existing = conn.execute(
                """
                SELECT id FROM deferred_llm_work
                WHERE dedup_key = ? AND status = 'pending'
                LIMIT 1
                """,
                (dedup_key,),
            ).fetchone()
            if existing:
                return int(existing["id"])
        cur = conn.execute(
            """
            INSERT INTO deferred_llm_work (
                work_type, priority, pool, payload, reason, status,
                attempts, max_attempts, next_attempt_at, dedup_key,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 'pending', 0, ?, ?, ?, ?, ?)
            """,
            (
                work_type,
                priority,
                pool,
                json.dumps(payload or {}),
                reason,
                int(max_attempts),
                next_at,
                dedup_key,
                now,
                now,
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_due_deferred_work(db_url: str, *, limit: int = 25) -> list[dict[str, Any]]:
    """Return pending deferred-work rows whose next_attempt_at has arrived."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        rows = conn.execute(
            """
            SELECT * FROM deferred_llm_work
            WHERE status = 'pending' AND next_attempt_at <= ?
            ORDER BY
                CASE priority
                    WHEN 'P0' THEN 0 WHEN 'P1' THEN 1
                    WHEN 'P2' THEN 2 ELSE 3 END,
                next_attempt_at ASC
            LIMIT ?
            """,
            (now, int(limit)),
        ).fetchall()
    out: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        try:
            item["payload"] = json.loads(item.get("payload") or "{}")
        except Exception:
            item["payload"] = {}
        out.append(item)
    return out


def count_pending_deferred_work(db_url: str, *, pool: str | None = None) -> int:
    """Count pending deferred-work rows (optionally scoped to a pool)."""
    conn = _get_conn(db_url)
    with _db_lock:
        if pool:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM deferred_llm_work "
                "WHERE status = 'pending' AND pool = ?",
                (pool,),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) AS n FROM deferred_llm_work WHERE status = 'pending'",
            ).fetchone()
    return int(row["n"]) if row else 0


def reschedule_deferred_work(
    db_url: str, row_id: int, *, next_attempt_at: str, reason: str = ""
) -> None:
    """Bump a deferred row's attempt count and next retry time (re-park)."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """
            UPDATE deferred_llm_work
            SET attempts = attempts + 1,
                next_attempt_at = ?,
                reason = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (next_attempt_at, reason, now, row_id),
        )
        conn.commit()


def finalize_deferred_work(
    db_url: str, row_id: int, *, status: str, reason: str = ""
) -> None:
    """Mark a deferred row terminal: 'done', 'failed', or 'abandoned'."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """
            UPDATE deferred_llm_work
            SET status = ?, reason = ?, updated_at = ?
            WHERE id = ?
            """,
            (status, reason, now, row_id),
        )
        conn.commit()


# ── Circuit-breaker state persistence (restore on boot) ──────────────────────


def save_circuit_state(
    db_url: str,
    *,
    agent_id: str,
    state: str,
    cooldown_until: float | None,
    tripped_at: float | None,
    reason: str,
    failure_count: int,
    cooldown_sec: int,
) -> None:
    """Upsert the current circuit-breaker state for an agent."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """
            INSERT INTO circuit_breaker_state (
                agent_id, state, cooldown_until, tripped_at, reason,
                failure_count, cooldown_sec, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(agent_id) DO UPDATE SET
                state = excluded.state,
                cooldown_until = excluded.cooldown_until,
                tripped_at = excluded.tripped_at,
                reason = excluded.reason,
                failure_count = excluded.failure_count,
                cooldown_sec = excluded.cooldown_sec,
                updated_at = excluded.updated_at
            """,
            (
                agent_id,
                state,
                cooldown_until,
                tripped_at,
                reason,
                int(failure_count),
                int(cooldown_sec),
                now,
            ),
        )
        conn.commit()


def clear_circuit_state(db_url: str, agent_id: str) -> None:
    """Remove persisted circuit state for an agent (on reset/restore)."""
    conn = _get_conn(db_url)
    with _db_lock:
        conn.execute(
            "DELETE FROM circuit_breaker_state WHERE agent_id = ?",
            (agent_id,),
        )
        conn.commit()


def load_open_circuit_states(db_url: str) -> list[dict[str, Any]]:
    """Return persisted circuit states that are still OPEN (for boot restore)."""
    conn = _get_conn(db_url)
    with _db_lock:
        try:
            rows = conn.execute(
                """
                SELECT * FROM circuit_breaker_state
                WHERE state = 'open'
                """,
            ).fetchall()
        except Exception:
            return []
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Conversation persistence
# ---------------------------------------------------------------------------


def save_conversation_turn(
    db_url: str,
    agent_id: str,
    role: str,
    content: str,
    metadata: dict[str, Any] | None = None,
    channel: str = "chat",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO conversations
               (agent_id, role, content, metadata_json,
                channel, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                role,
                content,
                json.dumps(metadata or {}),
                channel,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_conversation_history(
    db_url: str,
    agent_id: str,
    limit: int = 50,
    offset: int = 0,
    channel: str | None = None,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    with _db_lock:
        if channel:
            rows = conn.execute(
                """SELECT id, role, content, metadata_json,
                          channel, created_at
                   FROM conversations
                   WHERE agent_id = ?
                     AND (channel = ? OR channel IS NULL)
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (agent_id, channel, limit, offset),
            ).fetchall()
        else:
            # Exclude autopilot entries by default
            rows = conn.execute(
                """SELECT id, role, content, metadata_json,
                          channel, created_at
                   FROM conversations
                   WHERE agent_id = ?
                     AND (channel != 'autopilot'
                          OR channel IS NULL)
                   ORDER BY created_at DESC
                   LIMIT ? OFFSET ?""",
                (agent_id, limit, offset),
            ).fetchall()
    result = []
    for row in reversed(rows):
        result.append(
            {
                "id": row["id"],
                "role": row["role"],
                "content": row["content"],
                "metadata": json.loads(row["metadata_json"] or "{}"),
                "channel": row["channel"] or "chat",
                "created_at": row["created_at"],
            }
        )
    return result


def search_conversations(
    db_url: str,
    query: str,
    agent_id: str | None = None,
    channel: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    q = str(query or "").strip()
    lim = max(1, min(500, int(limit or 20)))
    ch = str(channel or "").strip().lower() or None

    clauses: list[str] = []
    params: list[Any] = []

    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)

    clauses.append("content LIKE ?")
    params.append(f"%{q}%")

    if ch and ch not in {"all"}:
        if ch == "sms":
            clauses.append("channel = 'sms'")
        elif ch == "autopilot":
            clauses.append("channel = 'autopilot'")
        elif ch == "web":
            clauses.append("(channel LIKE ? OR channel IS NULL OR channel = '')")
            params.append("%_chat")
        else:
            clauses.append("channel = ?")
            params.append(ch)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    with _db_lock:
        rows = conn.execute(
            """SELECT id, agent_id, role, content, created_at, channel
               FROM conversations""" + where + " ORDER BY created_at DESC LIMIT ?",
            tuple([*params, lim]),
        ).fetchall()
    return [dict(row) for row in rows]


def list_conversations(
    db_url: str,
    *,
    agent_id: str | None = None,
    channel: str | None = None,
    limit: int = 200,
    offset: int = 0,
    order: str = "desc",
) -> list[dict[str, Any]]:
    """List conversation turns with optional agent/channel filtering.

    Channel grouping:
      - sms: channel == 'sms'
      - autopilot: channel == 'autopilot'
      - web: channel LIKE '%_chat' OR channel IS NULL/empty
      - all: no filter
    """
    conn = _get_conn(db_url)

    lim = max(1, min(2000, int(limit or 200)))
    off = max(0, int(offset or 0))
    ord_norm = str(order or "desc").strip().lower()
    ord_sql = "ASC" if ord_norm == "asc" else "DESC"

    ch = str(channel or "").strip().lower() or None

    clauses: list[str] = []
    params: list[Any] = []

    if agent_id:
        clauses.append("agent_id = ?")
        params.append(agent_id)

    if ch and ch not in {"all"}:
        if ch == "sms":
            clauses.append("channel = 'sms'")
        elif ch == "autopilot":
            clauses.append("channel = 'autopilot'")
        elif ch == "web":
            clauses.append("(channel LIKE ? OR channel IS NULL OR channel = '')")
            params.append("%_chat")
        else:
            clauses.append("channel = ?")
            params.append(ch)

    where = " WHERE " + " AND ".join(clauses) if clauses else ""

    sql = (
        "SELECT id, agent_id, role, content, metadata_json, channel, created_at "
        "FROM conversations"
        + where
        + f" ORDER BY created_at {ord_sql} LIMIT ? OFFSET ?"
    )

    with _db_lock:
        rows = conn.execute(sql, tuple([*params, lim, off])).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        try:
            d["metadata"] = json.loads(d.pop("metadata_json", "{}") or "{}")
        except Exception:
            d["metadata"] = {}
            d.pop("metadata_json", None)
        out.append(d)
    return out


def list_conversation_agent_stats(
    db_url: str,
    *,
    limit: int = 200,
) -> list[dict[str, Any]]:
    """Return per-agent counts for conversation threads."""
    conn = _get_conn(db_url)
    lim = max(1, min(2000, int(limit or 200)))
    with _db_lock:
        rows = conn.execute(
            """SELECT agent_id,
                      COUNT(*) as count,
                      MAX(created_at) as last_created_at
               FROM conversations
               GROUP BY agent_id
               ORDER BY count DESC
               LIMIT ?""",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Memory (persistent, searchable, categorized)
# ---------------------------------------------------------------------------


def add_memory(
    db_url: str,
    content: str,
    category: str = "general",
    tags: list[str] | None = None,
    importance: int = 5,
    agent_id: str = "orchestrator",
    source: str = "manual",
    memory_type: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> int:
    from app.memory_contract import record_memory

    return record_memory(
        db_url,
        content,
        agent_id=agent_id,
        category=category,
        tags=tags,
        importance=importance,
        source=source,
        memory_type=memory_type,
        metadata=metadata,
    )


def search_memories(
    db_url: str,
    query: str,
    agent_id: str | None = None,
    category: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    conditions = ["content LIKE ?"]
    params: list[Any] = [f"%{query}%"]
    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)
    if category:
        conditions.append("category = ?")
        params.append(category)
    params.append(limit)
    where = " AND ".join(conditions)
    with _db_lock:
        rows = conn.execute(
            f"""SELECT id, agent_id, source, content, tags_json,
                       importance, category, created_at
                FROM memories
                WHERE {where}
                ORDER BY importance DESC, created_at DESC
                LIMIT ?""",
            params,
        ).fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "id": row["id"],
                "agent_id": row["agent_id"],
                "source": row["source"],
                "content": row["content"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "importance": row["importance"],
                "category": row["category"],
                "created_at": row["created_at"],
            }
        )
    return result


def get_recent_memories(
    db_url: str,
    limit: int = 20,
    agent_id: str = "orchestrator",
    category: str | None = None,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    if category:
        sql = """SELECT * FROM memories
                 WHERE agent_id = ? AND category = ?
                 ORDER BY created_at DESC LIMIT ?"""
        params: tuple = (agent_id, category, limit)
    else:
        sql = """SELECT * FROM memories
                 WHERE agent_id = ?
                 ORDER BY created_at DESC LIMIT ?"""
        params = (agent_id, limit)
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in reversed(rows):
        result.append(
            {
                "id": row["id"],
                "source": row["source"],
                "content": row["content"],
                "tags": json.loads(row["tags_json"] or "[]"),
                "importance": row["importance"],
                "category": row["category"],
                "created_at": row["created_at"],
            }
        )
    return result


# ---------------------------------------------------------------------------
# Task management
# ---------------------------------------------------------------------------


def _task_title_words(title: Any) -> set[str]:
    return {
        word
        for word in re.findall(r"[a-z0-9]+", str(title or "").lower())
        if len(word) > 2
    }


def _parse_task_timestamp(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


_TASK_LIFECYCLE_ACTIVE_STATUSES = ("open", "in_progress", "pending", "blocked")

_TASK_LIFECYCLE_AGENT_DOMAINS: dict[str, str] = {
    "orchestrator": "executive_operations",
    "dept_business_ops": "business_operations",
    "dept_finance": "finance",
    "finance_accountant": "finance",
    "finance_bookkeeper": "finance",
    "finance_controller": "finance",
    "finance_reconciliation_lead": "finance",
    "finance_source_steward": "finance",
    "reconciliation": "finance",
    "dept_engineering": "engineering",
    "dept_research": "research",
    "dept_home_life": "home_life",
    "dept_devices": "device_operations",
    "dept_security": "security",
}

_TASK_LIFECYCLE_KEYWORD_DOMAINS: list[tuple[str, tuple[str, ...]]] = [
    (
        "business_operations",
        (
            "phone & tech",
            "phone tech",
            "lpt",
            "customer",
            "referral",
            "repair",
            "work order",
            "revenue",
            "growth",
        ),
    ),
    (
        "procurement",
        ("alibaba", "supplier", "quote", "procurement", "sourcing", "inventory"),
    ),
    (
        "device_operations",
        (
            "e4610",
            "e4810",
            "kyocera",
            "flip phone",
            "matvt",
            "device",
            "iphone",
            "samsung",
        ),
    ),
    (
        "engineering",
        (
            "ci/cd",
            "pipeline",
            "github",
            "api",
            "dashboard",
            "system health",
            "queue job",
            "build",
            "deploy",
        ),
    ),
    (
        "finance",
        (
            "quickbooks",
            "qb",
            "reconciliation",
            "cfo",
            "invoice",
            "ledger",
            "cash",
            "budget",
        ),
    ),
    (
        "home_life",
        ("home assistant", "ha alert", "door", "sensor", "calendar", "reminder"),
    ),
    ("research", ("research", "directive", "source", "strategy")),
]


def _load_task_metadata(raw_metadata: Any) -> dict[str, Any]:
    if isinstance(raw_metadata, dict):
        return dict(raw_metadata)
    try:
        loaded = json.loads(str(raw_metadata or "{}"))
    except (TypeError, json.JSONDecodeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _task_lifecycle_owner(task: dict[str, Any]) -> str:
    return str(
        task.get("assigned_to")
        or task.get("agent_id")
        or task.get("delegated_from")
        or "orchestrator"
    )


def _task_lifecycle_domain(task: dict[str, Any], owner: str) -> str:
    text = " ".join(
        str(task.get(field) or "").lower()
        for field in ("title", "description", "tags_json")
    )
    for domain, keywords in _TASK_LIFECYCLE_KEYWORD_DOMAINS:
        if any(keyword in text for keyword in keywords):
            return domain
    return _TASK_LIFECYCLE_AGENT_DOMAINS.get(owner, "general_operations")


def _task_lifecycle_next_action(
    task: dict[str, Any],
    metadata: dict[str, Any],
    existing_lifecycle: dict[str, Any],
) -> str:
    explicit = metadata.get("next_action") or existing_lifecycle.get("next_action")
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()[:280]

    description = str(task.get("description") or "")
    for line in description.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        if candidate.lower().startswith(("next action:", "next:")):
            return candidate.split(":", 1)[1].strip()[:280] or candidate[:280]

    title = str(task.get("title") or "task").strip()
    status = str(task.get("status") or "open")
    if status == "open":
        return f"Claim, schedule, or delegate: {title}"[:280]
    if status == "in_progress":
        return f"Continue work and record progress/evidence: {title}"[:280]
    if status in {"pending", "blocked"}:
        return f"Resolve blocker, reroute, or close with evidence: {title}"[:280]
    return f"Review lifecycle state: {title}"[:280]


def _task_lifecycle_freshness_status(task: dict[str, Any]) -> str:
    status = str(task.get("status") or "open")
    if status in TASK_COMPLETED_STATUSES:
        return "closed"
    reference_time = _parse_task_timestamp(task.get("updated_at"))
    if reference_time is None:
        reference_time = _parse_task_timestamp(task.get("created_at"))
    if reference_time is None:
        return "unknown"
    age = datetime.now(timezone.utc) - reference_time
    if age >= timedelta(days=7):
        return "stale"
    if age >= timedelta(hours=48):
        return "review"
    return "fresh"


def _task_is_age_only(task: dict[str, Any]) -> bool:
    """True when the task's only difference from its creation is elapsed time.

    A ROW THAT HAS NOT MOVED IS NOT NEWS. Measured 2026-10-19: five owner-facing approval items
    in one session, four of them about work already done. Their evidence was task rows whose
    entire content was "[AUTO] Stale: no progress for N days" plus "0% progress" -- rows that had
    never been started and had not changed except the date. This function is how the governor
    says so in data, so no producer has to infer it from prose.

    Movement is a fact about the row, not about the clock: a start, any progress, or a real edit
    after creation (more than a minute, so a created-and-labelled row is not called "moved").
    """
    status = str(task.get("status") or "open")
    if status in TASK_COMPLETED_STATUSES or status in (
            "cancelled", "canceled", "superseded"):
        return False
    if task.get("started_at"):
        return False
    try:
        if int(task.get("progress_pct") or 0) > 0:
            return False
    except (TypeError, ValueError):
        pass
    # The old staleness flag rewrote updated_at while appending its marker, which made the very
    # rows it flagged look freshly handled. Its marker is therefore evidence of NO movement.
    if "[AUTO] Stale" in str(task.get("description") or ""):
        return True
    created = _parse_task_timestamp(task.get("created_at"))
    updated = _parse_task_timestamp(task.get("updated_at"))
    if created is not None and updated is not None:
        if updated - created > timedelta(minutes=1):
            return False
    return True


def _task_lifecycle_auto_close_evidence(task: dict[str, Any]) -> dict[str, Any]:
    status = str(task.get("status") or "open")
    title = str(task.get("title") or "")
    reference_time = _parse_task_timestamp(task.get("updated_at"))
    if reference_time is None:
        reference_time = _parse_task_timestamp(task.get("created_at"))

    if status in TASK_COMPLETED_STATUSES:
        return {
            "state": "closed",
            "reason": "task already completed",
            "completed_at": task.get("completed_at"),
        }

    if reference_time is not None:
        age = datetime.now(timezone.utc) - reference_time
        age_only = _task_is_age_only(task)
        if title.upper().startswith("APPROVAL:") and age >= timedelta(hours=4):
            if age_only:
                # AGE IS NOT A DECISION. An approval artifact nobody ever started is not "ready"
                # to close on the strength of its birthday; it is a row with no evidence at all.
                return {
                    "state": "review_required",
                    "age_only": True,
                    "reason": "AGE ONLY: the approval artifact has not moved since it was "
                              "created; being older is not evidence that it was handled",
                    "reference_at": task.get("updated_at") or task.get("created_at"),
                }
            return {
                "state": "ready",
                "age_only": False,
                "reason": "stale internal approval artifact older than 4 hours",
                "reference_at": task.get("updated_at") or task.get("created_at"),
            }
        if age >= timedelta(days=7):
            return {
                "state": "review_required",
                "age_only": age_only,
                "reason": ("AGE ONLY: nothing has changed except the date; this is not grounds "
                           "for a customer message or an approval item"
                           if age_only else "active task has no update for 7+ days"),
                "reference_at": task.get("updated_at") or task.get("created_at"),
            }

    return {
        "state": "none",
        "reason": "no completion, supersession, or stale-close evidence yet",
    }


def _infer_task_lifecycle(
    task: dict[str, Any],
    metadata: dict[str, Any] | None = None,
    *,
    refreshed_at: str | None = None,
) -> dict[str, Any]:
    metadata = metadata or _load_task_metadata(task.get("metadata_json"))
    existing_lifecycle = metadata.get("lifecycle")
    if not isinstance(existing_lifecycle, dict):
        existing_lifecycle = {}
    owner = _task_lifecycle_owner(task)
    domain = _task_lifecycle_domain(task, owner)
    return {
        "schema_version": 1,
        "owner": owner,
        "domain": domain,
        "next_action": _task_lifecycle_next_action(task, metadata, existing_lifecycle),
        "freshness_status": _task_lifecycle_freshness_status(task),
        # The label above is allowed to come from age. `age_only` says whether age is ALL it is;
        # a producer that is about to write to the owner or a customer must read this and stop.
        "age_only": _task_is_age_only(task),
        "auto_close_evidence": _task_lifecycle_auto_close_evidence(task),
        "source": "task_lifecycle_governor",
        "refreshed_at": refreshed_at or _now_iso(),
    }


def ensure_task_lifecycle_metadata(db_url: str) -> dict[str, Any]:
    """Backfill lifecycle metadata for active tasks without resetting freshness.

    The task's own ``updated_at`` is deliberately left untouched. Lifecycle
    refreshes should not make stale work look fresh.
    """
    conn = _get_conn(db_url)
    refreshed_at = _now_iso()
    with _db_lock:
        rows = conn.execute(
            """SELECT id, agent_id, title, description, status, priority,
                      due_date, completed_at, assigned_to, delegated_from,
                      tags_json, metadata_json, created_at, updated_at
               FROM tasks
               WHERE status IN ('open', 'in_progress', 'pending', 'blocked')
               ORDER BY created_at DESC LIMIT 1000""",
        ).fetchall()

        updated = 0
        missing_before = 0
        for row in rows:
            task = dict(row)
            metadata = _load_task_metadata(task.get("metadata_json"))
            existing_lifecycle = metadata.get("lifecycle")
            required_keys = {
                "owner",
                "domain",
                "next_action",
                "freshness_status",
                "auto_close_evidence",
            }
            if not isinstance(existing_lifecycle, dict) or not required_keys.issubset(
                set(existing_lifecycle)
            ):
                missing_before += 1
            lifecycle = _infer_task_lifecycle(
                task,
                metadata,
                refreshed_at=refreshed_at,
            )
            if existing_lifecycle == lifecycle:
                continue
            metadata["lifecycle"] = lifecycle
            conn.execute(
                "UPDATE tasks SET metadata_json = ? WHERE id = ?",
                (json.dumps(metadata), task["id"]),
            )
            updated += 1
        conn.commit()

    return {
        "scanned": len(rows),
        "updated": updated,
        "missing_before": missing_before,
        "refreshed_at": refreshed_at,
    }


def find_similar_open_tasks(
    db_url: str,
    title: str,
    agent_id: str | None = "orchestrator",
    similarity_threshold: int = 40,
) -> list[dict[str, Any]]:
    """Find active tasks with similar titles to prevent duplicates.

    Uses a simple word-overlap heuristic: if the ratio of shared words
    to total unique words exceeds *similarity_threshold* (0-100), the
    task is considered a match. Pass ``agent_id=None`` for a global scan.
    """
    conn = _get_conn(db_url)
    params: list[Any] = []
    query = (
        "SELECT id, title, priority, status, assigned_to, agent_id "
        "FROM tasks WHERE status IN (%s)"
        % ", ".join("?" * len(TASK_PENDING_WORK_STATUSES))
    )
    params.extend(TASK_PENDING_WORK_STATUSES)
    if agent_id is not None:
        query += " AND agent_id = ?"
        params.append(agent_id)
    query += " ORDER BY created_at DESC LIMIT 200"
    with _db_lock:
        rows = conn.execute(query, params).fetchall()

    title_words = _task_title_words(title)
    if not title_words:
        return []

    matches: list[dict[str, Any]] = []
    for row in rows:
        row_words = _task_title_words(row["title"])
        if not row_words:
            continue
        shared = title_words & row_words
        union = title_words | row_words
        pct = int(100 * len(shared) / len(union)) if union else 0
        if pct >= similarity_threshold:
            matches.append(
                {
                    "id": row["id"],
                    "title": row["title"],
                    "priority": row["priority"],
                    "status": row["status"],
                    "assigned_to": row["assigned_to"],
                    "agent_id": row["agent_id"],
                    "similarity_pct": pct,
                }
            )
    return matches


def _find_task_by_dedupe_key(db_url: str, dedupe_key: str) -> int | None:
    """Return the ID of an open/in_progress task with the given dedupe_key, or None."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT id FROM tasks WHERE dedupe_key = ? AND status IN ('open', 'in_progress') LIMIT 1",
            (dedupe_key,),
        ).fetchone()
    return row["id"] if row else None


def create_task(
    db_url: str,
    title: str,
    description: str = "",
    priority: str = "medium",
    due_date: str | None = None,
    tags: list[str] | None = None,
    agent_id: str = "orchestrator",
    assigned_to: str | None = None,
    delegated_from: str | None = None,
    mission_id: int | None = None,
    metadata: dict[str, Any] | None = None,
    dedup_threshold: int = 80,
    dedupe_key: str | None = None,
    bypass_ceiling: bool = False,
) -> int:
    # ── D012: dedup — skip duplicate open tasks ──
    assigned_to = canonicalize_assignment_agent(assigned_to)
    # ── Self-assignment safety gate ──
    if assigned_to and assigned_to == agent_id:
        try:
            from app.company_blueprint import get_agent_hierarchy_layer
            layer = get_agent_hierarchy_layer(agent_id)
            if layer in ("indexer", "clerk", "scout", "reviewer"):
                _log.warning(
                    "Blocked self-assignment: %s (%s) tried to create task for itself: %s",
                    agent_id, layer, title,
                )
                # Don't block — just force unassigned so the task exists but isn't self-referential
                assigned_to = None
        except Exception:
            pass

    # ── Exact dedup by dedupe_key (stronger than fuzzy title match) ──
    if dedupe_key:
        try:
            existing = _find_task_by_dedupe_key(db_url, dedupe_key)
            if existing is not None:
                _log.debug(
                    "Task dedup (exact): dedupe_key='%s' matches open task #%d",
                    dedupe_key,
                    existing,
                )
                return existing
        except Exception:
            pass  # dedup is best-effort

    if dedup_threshold > 0:
        try:
            # agent_id=None: a duplicate is a duplicate whoever filed it. Scoping this to
            # the caller let dept_finance create #25174 against orchestrator's #25106 at
            # 80% word overlap without either side noticing.
            dupes = find_similar_open_tasks(
                db_url,
                title,
                agent_id=None,
                similarity_threshold=dedup_threshold,
            )
            if dupes:
                _log.debug(
                    "Task dedup: '%s' matches open task #%d (%d%% similar)",
                    title,
                    dupes[0]["id"],
                    dupes[0]["similarity_pct"],
                )
                return dupes[0]["id"]
        except Exception:
            pass  # dedup is best-effort

    # ── Active-task ceiling gate ──
    # All creation paths (LLM tool calls, initiative_tick, standing work
    # orders) route through this function, so the ceiling check lives here
    # rather than in individual callers. Returns -1 when blocked so callers
    # can distinguish "blocked" from "dedup matched existing task".
    try:
        from app.services.task_protection import active_task_ceiling

        _ceiling = active_task_ceiling()
        _active = count_active_tasks_for_capacity(db_url)
        # `bypass_ceiling` is for the one class that MUST always be recordable:
        # an approval request. Measured 2026-10-26 -- the company sat at 300/300
        # and a refusal that tried to queue its approval got -1, so the request
        # vanished and the work could never be authorised. A gate that silently
        # drops the request to open a gate is a dead end with no trace. The flood
        # risk is bounded by the exact `dedupe_key` (one open row per action,
        # agent and resource) plus the 48h approval expiry.
        if _active >= _ceiling and not bypass_ceiling:
            _log.warning(
                "Task creation blocked: %d active tasks (ceiling %d). "
                "Caller=%s title=%s",
                _active, _ceiling, agent_id, title,
            )
            return -1
    except Exception:
        pass  # ceiling check is best-effort

    conn = _get_conn(db_url)
    now = _now_iso()
    task_metadata = dict(metadata or {})
    if dedupe_key:
        task_metadata["dedupe_key"] = dedupe_key
    provisional_task = {
        "agent_id": agent_id,
        "title": title,
        "description": description,
        "status": "open",
        "priority": priority,
        "due_date": due_date,
        "assigned_to": assigned_to,
        "delegated_from": delegated_from,
        "tags_json": json.dumps(tags or []),
        "metadata_json": json.dumps(task_metadata),
        "created_at": now,
        "updated_at": now,
    }
    task_metadata.setdefault(
        "lifecycle",
        _infer_task_lifecycle(
            provisional_task,
            task_metadata,
            refreshed_at=now,
        ),
    )
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO tasks
               (agent_id, title, description, status, priority, due_date,
                assigned_to, delegated_from, mission_id,
                tags_json, metadata_json, created_at, updated_at, dedupe_key)
               VALUES (?, ?, ?, 'open', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                title,
                description,
                priority,
                due_date,
                assigned_to,
                delegated_from,
                mission_id,
                json.dumps(tags or []),
                json.dumps(task_metadata),
                now,
                now,
                dedupe_key,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def set_task_mission(
    db_url: str,
    task_id: int,
    *,
    mission_id: int | None,
) -> bool:
    """Link/unlink a task to a mission (OKR alignment)."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            "UPDATE tasks SET mission_id = ?, updated_at = ? WHERE id = ?",
            (mission_id, now, task_id),
        )
        conn.commit()
        return cur.rowcount > 0


def _task_open_protection_reason(conn: Any, task_id: int) -> str:
    """Why a task with no work session at all must not be closed, or "".

    Reads the task's own row and defers to
    `app.services.task_protection.age_close_protection_reason`: the owner's task,
    money, a deadline, an explicit reopen.

    A task whose own progress says 100 is treated as carrying evidence and is
    allowed through: the autopilot's completion path writes `progress_pct=100`
    immediately before it closes the task and only after its own artefact check
    (`app/autopilot.py`, the `[WORK_DONE]` branch), and
    `_close_completed_progress_tasks` closes on the same signal.

    Anything that cannot be read returns "" -- the caller's invariant is that a
    check which cannot run never blocks a close.
    """
    try:
        from app.services.task_protection import age_close_protection_reason

        row = conn.execute(
            """SELECT id, title, description, due_date, assigned_to, agent_id,
                      delegated_from, tags_json, metadata_json, progress_pct
                 FROM tasks WHERE id = ?""",
            (int(task_id),),
        ).fetchone()
        if not row:
            return ""
        try:
            if int(row["progress_pct"] or 0) >= 100:
                return ""
        except (IndexError, KeyError, TypeError, ValueError):
            pass
        return age_close_protection_reason(row)
    except Exception:  # noqa: BLE001 - an unanswerable check must not block a close
        return ""


def _task_close_would_be_a_lie(
    conn: Any,
    task_id: int,
    *,
    within_hours: int = 24,
) -> str:
    """Why closing this task as done would record work that did not happen, or "".

    Measured 2026-09-15: tasks #25106 (five failed work sessions, none successful) and
    #25118 (three failed, none successful) were both set to 'done' by rollups. #25106 is
    a real $167.96 PayPal dispute with a hard deadline, and its goal plan had gone to
    'failed' -- the task was closed anyway. Nothing retries a task that is done and
    nothing raises, so a false 'done' buries the work permanently.

    Returns "" (allow) unless no session is ACTIVE and none completed recently, and
    either (a) at least one recent failure, or (b) no session has ever been recorded
    and the task is the owner's, carries money or a deadline, or was explicitly
    reopened. Measured 2026-10-02 (journal D2907): case (b) used to allow by default,
    and 27097 -- the owner's own "check the credit card statements" instruction --
    was closed done with no finding. A failure of this check itself returns "" -- a
    close must never be blocked because the check could not run.
    """
    from datetime import datetime, timedelta, timezone

    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max(1, int(within_hours)))
        ).isoformat()
        row = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'active') AS active,
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'failed' AND started_at >= ?) AS failed,
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'completed' AND started_at >= ?)
                AS completed,
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ?) AS total
            """,
            (
                int(task_id),
                int(task_id),
                cutoff,
                int(task_id),
                cutoff,
                int(task_id),
            ),
        ).fetchone()
    except Exception:  # noqa: BLE001 - an unanswerable check must not block a close
        return ""
    if not row:
        return ""
    active, failed, completed = (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
    if active or completed:
        return ""
    if failed:
        return (
            f"{failed} recent work session(s) failed and none succeeded, and no "
            "session is active now"
        )
    # The zero-session case. Measured 2026-10-02 (journal D2907): this used to
    # return "" (allow) here, which made the task nobody had ever touched the
    # one task nothing protected -- 27097, the owner's own "check the credit
    # card statements" instruction, was closed done with no finding.
    try:
        total = int(row[3] or 0)
    except (IndexError, TypeError, ValueError):
        return ""
    if total == 0:
        protection = _task_open_protection_reason(conn, int(task_id))
        if protection:
            return (
                "no work session has ever been recorded for this task and it "
                f"{protection}; closing it would record work that did not happen"
            )
    return ""


def _task_has_recorded_result(conn: Any, task_id: int) -> bool:
    """Whether any non-empty result is recorded against this task.

    Two indexed sources, both keyed on ``task_id``: a delegation carrying a
    non-empty ``result_summary``, and a work session that completed or wrote a
    non-empty ``output_log``.

    ``goal_steps`` is deliberately **not** consulted, and the incident row is why.
    Measured 2026-10-06: goal step 46688 was stamped ``status='completed'`` with
    ``output_json = {"action": "complete", ...}`` while its ``result_summary`` was
    a non-empty envelope reading ``{"action": "escalate", "result_summary": "The
    Mashgiach department cannot directly review the Sticky Brand print proof
    ..."}`` -- a refusal to act, stored as though it were the act. The step's
    ``action`` came from an unparseable-reply fallback that hardcodes
    ``action="complete"`` (``app/services/agent_worker.py::_parse_final_response``,
    line 3437), so neither field there is evidence that work happened. Reading it
    would also put an unindexed scan of ``goal_plans`` (35,613 rows, no index on
    ``parent_task_id``) on every close.

    An unreadable check returns True: this codebase's rule for a guard is that a
    check which cannot run never blocks a close.
    """
    try:
        row = conn.execute(
            """
            SELECT 1
            FROM delegations
            WHERE task_id = ? AND TRIM(COALESCE(result_summary, '')) <> ''
            UNION ALL
            SELECT 1
            FROM work_sessions
            WHERE task_id = ?
              AND (status = 'completed' OR TRIM(COALESCE(output_log, '')) <> '')
            LIMIT 1
            """,
            (int(task_id), int(task_id)),
        ).fetchone()
    except Exception:  # noqa: BLE001 - a check that cannot run must not block a close
        return True
    return row is not None


def task_close_needs_result_reason(conn: Any, task_id: int) -> str:
    """Why this close is refused for a missing recorded result, or ``""``.

    The owner-action rule, added after the 2026-10-06 incident. Task #27694 --
    "Review Sticky Brand print proof for order #828330 (auto-print in 2 days)" --
    came from a triaged owner-facing email, was delegated to dept_mashgiach, and
    was closed ``done`` 66 minutes later while delegation 6065 was closed
    ``completed`` with ``result_summary = ''``. Nothing was reviewed and the owner
    was never told.

    The rule: a task whose origin is an owner-facing email action, or whose
    title/description states a decision, an approval or a deadline, is not
    markable done while no result is recorded against it. Measured 2026-10-13 over
    the live table: the marker matches 45 of 279 active and 1,707 of 28,076 done
    tasks, and refusing the 138 marker-matching done rows that carry no recorded
    result is 0.5% of all closes -- 9 rows in the last 7 days, about 1.3 a day
    against a company that ticks ~130 times a day.

    Anything that cannot be read returns "" -- the caller's invariant is that a
    check which cannot run never blocks a close.
    """
    try:
        from app.services.task_protection import result_required_reason

        row = conn.execute(
            """SELECT id, title, description, tags_json, metadata_json
                 FROM tasks WHERE id = ?""",
            (int(task_id),),
        ).fetchone()
        if not row:
            return ""
        # Pass a plain mapping: ``task_protection._row_get`` reads sqlite3.Row
        # and dict, and a connection built without a row factory would otherwise
        # yield a tuple, read as "no marker", and silently allow every close.
        marker = result_required_reason(
            dict(
                zip(
                    ("id", "title", "description", "tags_json", "metadata_json"),
                    tuple(row),
                )
            )
        )
        if not marker:
            return ""
        if _task_has_recorded_result(conn, int(task_id)):
            return ""
        return (
            f"{marker}, and no result is recorded for it (no delegation carries "
            "a non-empty result_summary and no work session completed or "
            "recorded output)"
        )
    except Exception:  # noqa: BLE001 - an unanswerable check must not block a close
        return ""


def update_task(
    db_url: str,
    task_id: int,
    status: str | None = None,
    title: str | None = None,
    description: str | None = None,
    priority: str | None = None,
    due_date: str | None = None,
    assigned_to: str | None = None,
    tags: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    suppress_origin_followup: bool = False,
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    completing = status in TASK_COMPLETED_STATUSES
    if completing:
        # Refuse a completion that rests on nothing but failure. See
        # _task_close_would_be_a_lie: four different rollup paths close tasks, so the rule
        # lives at the writer rather than in each of them.
        # Two independent refusals, both at the writer, because four different
        # rollup paths close tasks (see _task_close_would_be_a_lie). The second
        # is the owner-action rule added for the 2026-10-06 incident: a model
        # reply that could not be parsed was treated as a completion, the goal
        # rolled up 'completed', and the D016 bridge closed task #27694 and its
        # active delegation with delegations.result_summary left empty.
        _lie = _task_close_would_be_a_lie(
            conn, int(task_id)
        ) or task_close_needs_result_reason(conn, int(task_id))
        if _lie:
            logging.getLogger(__name__).warning(
                "update_task(%s): refusing to mark %r -- %s",
                task_id,
                status,
                _lie,
            )
            status = None
            completing = False
    assigned_to = canonicalize_assignment_agent(assigned_to)
    existing_task = get_task(db_url, task_id)
    updates: list[str] = []
    params: list[Any] = []
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status in TASK_COMPLETED_STATUSES:
            updates.append("completed_at = ?")
            params.append(now)
    if title is not None:
        updates.append("title = ?")
        params.append(title)
    if description is not None:
        updates.append("description = ?")
        params.append(description)
    if priority is not None:
        updates.append("priority = ?")
        params.append(priority)
    if due_date is not None:
        updates.append("due_date = ?")
        params.append(due_date)
    if assigned_to is not None:
        updates.append("assigned_to = ?")
        params.append(assigned_to)
    if tags is not None:
        updates.append("tags_json = ?")
        params.append(json.dumps(tags))
    if metadata is not None:
        updates.append("metadata_json = ?")
        params.append(json.dumps(metadata))
    if not updates:
        return False
    updates.append("updated_at = ?")
    params.append(now)
    params.append(task_id)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
            params,
        )

        # If a task completed, complete any active delegations for it.
        if completing and cur.rowcount:
            conn.execute(
                "UPDATE delegations "
                "SET status = 'completed', completed_at = ? "
                "WHERE task_id = ? AND status = 'active'",
                (now, task_id),
            )
        conn.commit()
        ok = cur.rowcount > 0

    if ok and completing and not suppress_origin_followup and existing_task is not None:
        try:
            from app.config import settings as app_settings
            from app.services.task_origin_followup import (
                maybe_send_task_origin_followup,
                stamp_task_origin_followup_metadata,
            )

            refreshed_task = get_task(db_url, task_id) or existing_task
            owner_notified = maybe_send_task_origin_followup(
                settings=app_settings,
                task=refreshed_task,
                new_status=status,
                progress_value=None,
            )
            if owner_notified:
                refreshed_metadata = stamp_task_origin_followup_metadata(
                    refreshed_task,
                    new_status=status,
                    progress_value=None,
                )
                with _db_lock:
                    conn.execute(
                        (
                            "UPDATE tasks SET metadata_json = ?, "
                            "updated_at = ? WHERE id = ?"
                        ),
                        (json.dumps(refreshed_metadata), _now_iso(), task_id),
                    )
                    conn.commit()
        except Exception as exc:
            _log.warning(
                ("Failed to send task-origin completion follow-up " "for task #%s: %s"),
                task_id,
                exc,
            )

    return ok


def list_tasks(
    db_url: str,
    agent_id: str | None = None,
    status: str | list[str] | tuple[str, ...] | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    mission_id: int | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    where, params = _build_task_filters(
        agent_id=agent_id,
        status=status,
        priority=priority,
        assigned_to=assigned_to,
        mission_id=mission_id,
    )
    conn = _get_conn(db_url)
    query_params = list(params)
    query_params.append(limit)
    with _db_lock:
        rows = conn.execute(
            f"""SELECT * FROM tasks {where}
                ORDER BY
                    CASE priority
                        WHEN 'urgent' THEN 0
                        WHEN 'critical' THEN 0
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 2
                        WHEN 'low' THEN 3
                        ELSE 4
                    END,
                    created_at DESC
                LIMIT ?""",
            query_params,
        ).fetchall()
    results = []
    for row in rows:
        d = dict(row)
        d["tags"] = json.loads(d.pop("tags_json", "[]"))
        d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
        results.append(d)
    return results


def _build_task_filters(
    *,
    agent_id: str | None = None,
    status: str | list[str] | tuple[str, ...] | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    mission_id: int | None = None,
) -> tuple[str, list[Any]]:
    conditions: list[str] = []
    params: list[Any] = []
    if agent_id:
        conditions.append("agent_id = ?")
        params.append(agent_id)
    if status:
        if isinstance(status, (list, tuple)):
            statuses = [str(value).strip() for value in status if str(value).strip()]
            if statuses:
                placeholders = ", ".join("?" for _ in statuses)
                conditions.append(f"status IN ({placeholders})")
                params.extend(statuses)
        else:
            conditions.append("status = ?")
            params.append(status)
    if priority:
        conditions.append("priority = ?")
        params.append(priority)
    if assigned_to:
        conditions.append("assigned_to = ?")
        params.append(assigned_to)
    if mission_id is not None:
        conditions.append("mission_id = ?")
        params.append(int(mission_id))
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    return where, params


def count_tasks(
    db_url: str,
    *,
    agent_id: str | None = None,
    status: str | list[str] | tuple[str, ...] | None = None,
    priority: str | None = None,
    assigned_to: str | None = None,
    mission_id: int | None = None,
) -> int:
    with _db_lock:
        conn = _get_conn(db_url)
        where, params = _build_task_filters(
            agent_id=agent_id,
            status=status,
            priority=priority,
            assigned_to=assigned_to,
            mission_id=mission_id,
        )
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM tasks {where}",
            params,
        ).fetchone()
    return int((row or {"c": 0})["c"])


def count_tasks_by_assignee(
    db_url: str,
    *,
    status: str | list[str] | tuple[str, ...] | None = None,
) -> dict[str, int]:
    conn = _get_conn(db_url)
    where, params = _build_task_filters(status=status)
    with _db_lock:
        rows = conn.execute(
            f"""SELECT COALESCE(NULLIF(assigned_to, ''), 'unassigned') AS assignee,
                       COUNT(*) AS c
                FROM tasks
                {where}
                GROUP BY COALESCE(NULLIF(assigned_to, ''), 'unassigned')""",
            params,
        ).fetchall()
    return {str(row["assignee"]): int(row["c"]) for row in rows}


def get_task_status_summary(
    db_url: str,
    *,
    agent_id: str | None = None,
    assigned_to: str | None = None,
    mission_id: int | None = None,
) -> dict[str, Any]:
    """Return authoritative task totals grouped by status."""
    conn = _get_conn(db_url)
    where, params = _build_task_filters(
        agent_id=agent_id,
        assigned_to=assigned_to,
        mission_id=mission_id,
    )
    with _db_lock:
        rows = conn.execute(
            f"SELECT status, COUNT(*) AS c FROM tasks {where} GROUP BY status",
            params,
        ).fetchall()

    by_status = {str(row["status"]): int(row["c"]) for row in rows}
    completed_total = sum(
        int(by_status.get(status, 0)) for status in TASK_COMPLETED_STATUSES
    )
    active_total = sum(int(by_status.get(status, 0)) for status in TASK_ACTIVE_STATUSES)
    return {
        "by_status": by_status,
        "completed_total": completed_total,
        "active_total": active_total,
        "total": sum(by_status.values()),
    }


def count_active_tasks_for_capacity(
    db_url: str,
    *,
    stale_in_progress_days: int = 5,
) -> int:
    """Count tasks consuming a create-task capacity slot.

    The status set is owned by ``app.services.task_protection`` (see
    ``TASK_CEILING_CONSUMING_STATUSES``): ``blocked`` is non-consuming and
    ``todo`` is consuming. Stale ``in_progress`` tasks stay visible to hygiene
    tooling but do not keep blocking new work forever; that escape is preserved.
    Round 4 moved the predicate here so the ceiling has one home.
    """
    from app.services.task_protection import count_consuming_tasks

    conn = _get_conn(db_url)
    with _db_lock:
        return count_consuming_tasks(
            conn, stale_in_progress_days=stale_in_progress_days
        )


def get_pipeline_activity_summary(db_url: str) -> dict[str, int]:
    """Return lightweight pipeline counts for live status reporting."""
    conn = _get_conn(db_url)
    summary = {
        "work_orders": 0,
        "goal_plans_24h": 0,
        "pending_steps": 0,
        "agent_ticks_24h": 0,
    }

    with _db_lock:
        try:
            summary["work_orders"] = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM standing_work_orders "
                    "WHERE is_enabled = 1"
                ).fetchone()["c"]
            )
        except Exception:
            pass

        try:
            summary["goal_plans_24h"] = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM goal_plans "
                    "WHERE created_at > strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')"
                ).fetchone()["c"]
            )
        except Exception:
            pass

        try:
            summary["pending_steps"] = int(
                conn.execute(
                    """SELECT COUNT(*) AS c
                       FROM goal_steps gs
                       JOIN goal_plans gp ON gp.id = gs.goal_id
                      WHERE gs.status IN ('pending', 'running')
                        AND gp.status IN ('active', 'pending')"""
                ).fetchone()["c"]
            )
        except Exception:
            pass

        try:
            summary["agent_ticks_24h"] = int(
                conn.execute(
                    "SELECT COUNT(*) AS c FROM tick_telemetry "
                    "WHERE started_at > strftime('%Y-%m-%dT%H:%M:%S', 'now', '-24 hours')"
                ).fetchone()["c"]
            )
        except Exception:
            pass

    return summary


def get_goal_status_counts(db_url: str) -> dict[str, int]:
    """Return goal plan counts grouped by status."""
    conn = _get_conn(db_url)
    counts: dict[str, int] = {}
    with _db_lock:
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM goal_plans " "GROUP BY status"
            ).fetchall()
            for row in rows:
                counts[row["status"]] = int(row["c"])
        except Exception:
            pass
    return counts


def deflate_task_priorities(
    db_url: str,
    *,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Deflate priority inflation for stale tasks.

    Rules (only when there is NO due date):
      - urgent/critical older than 24h → high
      - high older than 7d → medium

    Returns counts and supports dry-run for visibility.
    """
    conn = _get_conn(db_url)
    now = _now_iso()

    def _count(sql: str) -> int:
        row = conn.execute(sql).fetchone()
        try:
            return int(row[0] if row else 0)
        except Exception:
            return 0

    urgent_where = (
        "status = 'open' AND priority IN ('urgent', 'critical') "
        "AND (due_date IS NULL OR due_date = '') "
        "AND julianday(created_at) < julianday('now') - 1.0"
    )
    high_where = (
        "status = 'open' AND priority = 'high' "
        "AND (due_date IS NULL OR due_date = '') "
        "AND julianday(created_at) < julianday('now') - 7.0"
    )

    with _db_lock:
        would_urgent_to_high = _count(
            f"SELECT COUNT(*) FROM tasks WHERE {urgent_where}"
        )
        would_high_to_medium = _count(f"SELECT COUNT(*) FROM tasks WHERE {high_where}")

        updated_urgent_to_high = 0
        updated_high_to_medium = 0

        if not dry_run:
            cur1 = conn.execute(
                f"UPDATE tasks SET priority = 'high', updated_at = ? WHERE {urgent_where}",
                (now,),
            )
            updated_urgent_to_high = int(cur1.rowcount or 0)

            cur2 = conn.execute(
                f"UPDATE tasks SET priority = 'medium', updated_at = ? WHERE {high_where}",
                (now,),
            )
            updated_high_to_medium = int(cur2.rowcount or 0)

            conn.commit()

    return {
        "ok": True,
        "dry_run": bool(dry_run),
        "would_urgent_to_high": would_urgent_to_high,
        "would_high_to_medium": would_high_to_medium,
        "updated_urgent_to_high": updated_urgent_to_high,
        "updated_high_to_medium": updated_high_to_medium,
    }


def get_task(db_url: str, task_id: int) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["tags"] = json.loads(d.pop("tags_json", "[]"))
    d["metadata"] = json.loads(d.pop("metadata_json", "{}"))
    return d


def task_hygiene_report(db_url: str) -> dict[str, Any]:
    """Generate a task hygiene report for organizational awareness.

    Returns statistics that help the CEO understand the state of the
    active task backlog: duplicate clusters, assignment distribution,
    status/priority breakdowns, and staleness metrics.
    """
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT id, agent_id, title, description, priority, status,
                     assigned_to, due_date, completed_at, tags_json,
                     metadata_json, created_at, updated_at
                             FROM tasks WHERE status IN ('open', 'in_progress', 'pending', 'blocked')
               ORDER BY created_at DESC LIMIT 500""",
        ).fetchall()

    if not rows:
        return {
            "total_open": 0,
            "total_in_progress": 0,
            "total_active": 0,
            "by_priority": {},
            "by_status": {},
            "by_assignee": {},
            "duplicate_clusters": 0,
            "duplicate_cluster_details": [],
            "stale_tasks": 0,
            "stale_in_progress_tasks": 0,
            "stale_task_details": [],
            "completion_reconcile_candidates": 0,
            "completion_reconcile_details": [],
            "lifecycle_missing_count": 0,
            "lifecycle_missing_details": [],
            "by_lifecycle_owner": {},
            "by_lifecycle_domain": {},
            "by_lifecycle_freshness": {},
        }

    tasks = [dict(r) for r in rows]
    lifecycle_required_keys = {
        "owner",
        "domain",
        "next_action",
        "freshness_status",
        "auto_close_evidence",
    }

    lifecycle_missing_details = []
    by_lifecycle_owner: dict[str, int] = {}
    by_lifecycle_domain: dict[str, int] = {}
    by_lifecycle_freshness: dict[str, int] = {}
    for task in tasks:
        metadata = _load_task_metadata(task.get("metadata_json"))
        stored_lifecycle = metadata.get("lifecycle")
        if not isinstance(stored_lifecycle, dict):
            stored_lifecycle = {}
        missing_keys = sorted(lifecycle_required_keys - set(stored_lifecycle))
        if missing_keys:
            lifecycle_missing_details.append(
                {
                    "id": task["id"],
                    "title": task["title"],
                    "missing": missing_keys,
                }
            )
        computed_lifecycle = _infer_task_lifecycle(task, metadata)
        task["lifecycle"] = computed_lifecycle
        owner = computed_lifecycle.get("owner") or "unassigned"
        domain = computed_lifecycle.get("domain") or "general_operations"
        freshness = computed_lifecycle.get("freshness_status") or "unknown"
        by_lifecycle_owner[owner] = by_lifecycle_owner.get(owner, 0) + 1
        by_lifecycle_domain[domain] = by_lifecycle_domain.get(domain, 0) + 1
        by_lifecycle_freshness[freshness] = by_lifecycle_freshness.get(freshness, 0) + 1

    # Status breakdown
    by_status: dict[str, int] = {}
    for t in tasks:
        status = str(t.get("status") or "open")
        by_status[status] = by_status.get(status, 0) + 1

    # Priority breakdown
    by_priority: dict[str, int] = {}
    for t in tasks:
        p = t.get("priority") or "medium"
        by_priority[p] = by_priority.get(p, 0) + 1

    # Assignment distribution
    by_assignee: dict[str, int] = {}
    for t in tasks:
        a = t.get("assigned_to") or "unassigned"
        by_assignee[a] = by_assignee.get(a, 0) + 1

    # Duplicate clusters: group tasks with >40% word overlap
    clusters: list[list[dict[str, Any]]] = []
    used: set[int] = set()

    def _cluster_item(task: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": task["id"],
            "title": task["title"],
            "status": task.get("status"),
            "assigned_to": task.get("assigned_to"),
            "updated_at": task.get("updated_at"),
        }

    for i, t1 in enumerate(tasks):
        if t1["id"] in used:
            continue
        w1 = _task_title_words(t1["title"])
        if not w1:
            continue
        cluster = [_cluster_item(t1)]
        for t2 in tasks[i + 1 :]:
            if t2["id"] in used:
                continue
            w2 = _task_title_words(t2["title"])
            if not w2:
                continue
            overlap = len(w1 & w2) / len(w1 | w2) if (w1 | w2) else 0
            if overlap >= 0.4:
                cluster.append(_cluster_item(t2))
                used.add(t2["id"])
        if len(cluster) > 1:
            used.add(t1["id"])
            clusters.append(cluster)

    # Staleness: active tasks not updated in 7 days.
    now = datetime.now(timezone.utc)
    reconcile_cutoff = now - timedelta(hours=48)
    stale_cutoff = now - timedelta(days=7)
    stale_tasks = []
    reconcile_tasks = []
    for task in tasks:
        reference_time = _parse_task_timestamp(task.get("updated_at"))
        if reference_time is None:
            reference_time = _parse_task_timestamp(task.get("created_at"))
        if (
            task.get("status") == "in_progress"
            and reference_time is not None
            and reference_time < reconcile_cutoff
        ):
            reconcile_tasks.append(task)
        if reference_time is not None and reference_time < stale_cutoff:
            stale_tasks.append(task)

    stale_task_details = [
        {
            "id": task["id"],
            "title": task["title"],
            "status": task.get("status"),
            "assigned_to": task.get("assigned_to"),
            "updated_at": task.get("updated_at"),
        }
        for task in stale_tasks[:10]
    ]
    reconcile_task_details = [
        {
            "id": task["id"],
            "title": task["title"],
            "status": task.get("status"),
            "assigned_to": task.get("assigned_to"),
            "updated_at": task.get("updated_at"),
        }
        for task in reconcile_tasks[:10]
    ]

    return {
        "total_open": by_status.get("open", 0),
        "total_in_progress": by_status.get("in_progress", 0),
        "total_active": len(tasks),
        "by_status": by_status,
        "by_priority": by_priority,
        "by_assignee": by_assignee,
        "duplicate_clusters": len(clusters),
        "duplicate_cluster_details": clusters[:10],  # top 10
        "stale_tasks": len(stale_tasks),
        "stale_in_progress_tasks": sum(
            1 for task in stale_tasks if task.get("status") == "in_progress"
        ),
        "stale_task_details": stale_task_details,
        "completion_reconcile_candidates": len(reconcile_tasks),
        "completion_reconcile_details": reconcile_task_details,
        "lifecycle_missing_count": len(lifecycle_missing_details),
        "lifecycle_missing_details": lifecycle_missing_details[:10],
        "by_lifecycle_owner": by_lifecycle_owner,
        "by_lifecycle_domain": by_lifecycle_domain,
        "by_lifecycle_freshness": by_lifecycle_freshness,
    }


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


def upsert_knowledge(
    db_url: str,
    agent_id: str,
    topic: str,
    content: str,
    source: str = "learned",
    confidence: float = 0.5,
    tags: list[str] | None = None,
) -> dict[str, Any]:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        existing = conn.execute(
            "SELECT id FROM knowledge WHERE agent_id = ? AND topic = ?",
            (agent_id, topic),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE knowledge
                   SET content = ?, source = ?, confidence = ?,
                       tags_json = ?, updated_at = ?
                   WHERE id = ?""",
                (
                    content,
                    source,
                    confidence,
                    json.dumps(tags or []),
                    now,
                    existing["id"],
                ),
            )
            conn.commit()
            return {"id": existing["id"], "action": "updated", "topic": topic}
        else:
            cur = conn.execute(
                """INSERT INTO knowledge
                   (agent_id, topic, content, source, confidence,
                    tags_json, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    agent_id,
                    topic,
                    content,
                    source,
                    confidence,
                    json.dumps(tags or []),
                    now,
                    now,
                ),
            )
            conn.commit()
            return {"id": cur.lastrowid, "action": "created", "topic": topic}


def search_knowledge(
    db_url: str,
    query: str,
    agent_id: str | None = None,
    limit: int = 10,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    if agent_id:
        sql = """SELECT * FROM knowledge
                 WHERE agent_id = ? AND (topic LIKE ? OR content LIKE ?)
                 ORDER BY confidence DESC, updated_at DESC LIMIT ?"""
        params: tuple = (agent_id, f"%{query}%", f"%{query}%", limit)
    else:
        sql = """SELECT * FROM knowledge
                 WHERE topic LIKE ? OR content LIKE ?
                 ORDER BY confidence DESC, updated_at DESC LIMIT ?"""
        params = (f"%{query}%", f"%{query}%", limit)
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Credentials vault (stored in DB, not just .env)
# ---------------------------------------------------------------------------


def store_credential(
    db_url: str,
    service: str,
    key_name: str = "api_key",
    key_value: str = "",
    notes: str = "",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        existing = conn.execute(
            "SELECT id FROM credentials WHERE service = ? AND key_name = ?",
            (service, key_name),
        ).fetchone()
        if existing:
            conn.execute(
                """UPDATE credentials
                   SET key_value = ?, notes = ?, updated_at = ?
                   WHERE id = ?""",
                (key_value, notes, now, existing["id"]),
            )
            conn.commit()
            return existing["id"]
        else:
            cur = conn.execute(
                """INSERT INTO credentials
                   (service, key_name, key_value,
                    notes, created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (service, key_name, key_value, notes, now, now),
            )
            conn.commit()
            return cur.lastrowid or 0


def get_credential(
    db_url: str,
    service: str,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM credentials WHERE service = ?",
            (service,),
        ).fetchall()
    if not rows:
        return None
    if len(rows) == 1:
        return dict(rows[0])
    # Multiple keys for same service
    return {
        "service": service,
        "keys": [dict(r) for r in rows],
    }


def list_credentials(db_url: str) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT id, service, key_name, notes,
                      created_at, updated_at
               FROM credentials ORDER BY service""",
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Settings overrides
# ---------------------------------------------------------------------------


def list_settings_overrides(db_url: str) -> dict[str, Any]:
    """Return all persisted config overrides as python values."""
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT key, value_json, updated_at
               FROM settings_overrides
               ORDER BY key""",
        ).fetchall()

    out: dict[str, Any] = {}
    for row in rows:
        key = str(row["key"])
        raw = row["value_json"]
        try:
            out[key] = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            # Preserve raw value when JSON decode fails.
            out[key] = raw
    return out


def list_settings_overrides_entries(db_url: str) -> dict[str, dict[str, Any]]:
    """Return overrides keyed by setting, with value + updated_at."""
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT key, value_json, updated_at
               FROM settings_overrides
               ORDER BY key""",
        ).fetchall()

    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        key = str(row["key"])
        raw = row["value_json"]
        value: Any
        try:
            value = json.loads(raw) if isinstance(raw, str) else raw
        except (json.JSONDecodeError, TypeError, ValueError):
            value = raw
        out[key] = {
            "value": value,
            "updated_at": row["updated_at"],
        }
    return out


def upsert_settings_override(
    db_url: str,
    key: str,
    value: Any,
) -> str:
    """Create/update a config override. Returns updated_at (ISO)."""
    conn = _get_conn(db_url)
    now = _now_iso()
    try:
        value_json = json.dumps(value)
    except TypeError as exc:
        msg = f"Override value for {key!r} is not JSON-serializable"
        raise ValueError(msg) from exc

    with _db_lock:
        conn.execute(
            """INSERT INTO settings_overrides (key, value_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE
               SET value_json = excluded.value_json,
                   updated_at = excluded.updated_at""",
            (key, value_json, now),
        )
        conn.commit()
    return now


def delete_settings_override(db_url: str, key: str) -> bool:
    """Delete a config override. Returns True when something was removed."""
    conn = _get_conn(db_url)
    with _db_lock:
        cur = conn.execute(
            "DELETE FROM settings_overrides WHERE key = ?",
            (key,),
        )
        conn.commit()
        return bool(cur.rowcount)


# ---------------------------------------------------------------------------
# Activity log
# ---------------------------------------------------------------------------


def log_activity(
    db_url: str,
    action: str,
    detail: str = "",
    agent_id: str = "orchestrator",
    details: dict[str, Any] | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO activity_log
               (agent_id, action, detail, details_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (agent_id, action, detail, json.dumps(details or {}), now),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_recent_activity(
    db_url: str,
    agent_id: str | None = None,
    limit: int = 30,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    if agent_id:
        sql = """SELECT * FROM activity_log
                 WHERE agent_id = ?
                 ORDER BY created_at DESC LIMIT ?"""
        params: tuple = (agent_id, limit)
    else:
        sql = """SELECT * FROM activity_log
                 ORDER BY created_at DESC LIMIT ?"""
        params = (limit,)
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in reversed(rows):
        entry = dict(row)
        entry["details"] = json.loads(entry.pop("details_json", "{}"))
        result.append(entry)
    return result


# ---------------------------------------------------------------------------
# Bills / recurring payments
# ---------------------------------------------------------------------------


def list_bills(
    db_url: str,
    *,
    status: str = "pending",
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List bills, optionally filtered by status."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 100)))

    if status == "all":
        sql = "SELECT * FROM bills ORDER BY due_date ASC, updated_at DESC LIMIT ?"
        params: tuple[Any, ...] = (lim,)
    else:
        sql = (
            "SELECT * FROM bills WHERE status = ? "
            "ORDER BY due_date ASC, updated_at DESC LIMIT ?"
        )
        params = (status, lim)

    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Contacts
# ---------------------------------------------------------------------------


def list_contacts(
    db_url: str,
    *,
    query: str = "",
    limit: int = 200,
) -> list[dict[str, Any]]:
    """List contacts, optionally filtered by a free-text query."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 200)))

    q = str(query or "").strip()
    if q:
        like = f"%{q}%"
        sql = (
            "SELECT * FROM contacts "
            "WHERE name LIKE ? OR phone LIKE ? OR email LIKE ? "
            "ORDER BY favorite DESC, name ASC, updated_at DESC "
            "LIMIT ?"
        )
        params: tuple[Any, ...] = (like, like, like, lim)
    else:
        sql = (
            "SELECT * FROM contacts "
            "ORDER BY favorite DESC, name ASC, updated_at DESC "
            "LIMIT ?"
        )
        params = (lim,)

    with _db_lock:
        rows = conn.execute(sql, params).fetchall()

    out: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        tags_json = d.pop("tags_json", "[]")
        try:
            d["tags"] = json.loads(tags_json) if tags_json else []
        except Exception:
            d["tags"] = []
        out.append(d)
    return out


def create_contact(
    db_url: str,
    *,
    name: str,
    phone: str = "",
    email: str = "",
    address: str = "",
    company: str = "",
    role: str = "",
    notes: str = "",
    tags: list[str] | None = None,
    favorite: int | bool = 0,
    relationship: str | None = None,
    source: str | None = None,
) -> int:
    """Create a contact and return its ID."""
    conn = _get_conn(db_url)
    now = _now_iso()

    clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
    try:
        tags_json = json.dumps(clean_tags)
    except Exception:
        tags_json = "[]"

    try:
        fav = 1 if int(favorite) else 0
    except Exception:
        fav = 0

    address_val = (address or "").strip() or None
    company_val = (company or "").strip() or None
    role_val = (role or "").strip() or None
    notes_val = (notes or "").strip()
    relationship_val = (relationship or "").strip() or None
    source_val = (source or "").strip() or "manual"

    with _db_lock:
        cur = conn.execute(
            """INSERT INTO contacts
               (name, phone, email, address, company, role, notes, tags_json, favorite,
                relationship, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                name,
                (phone or "").strip() or None,
                (email or "").strip() or None,
                address_val,
                company_val,
                role_val,
                notes_val,
                tags_json,
                fav,
                relationship_val,
                source_val,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def update_contact(
    db_url: str,
    contact_id: int,
    *,
    name: str | None = None,
    phone: str | None = None,
    email: str | None = None,
    address: str | None = None,
    company: str | None = None,
    role: str | None = None,
    notes: str | None = None,
    tags: list[str] | None = None,
    favorite: int | bool | None = None,
    relationship: str | None = None,
    source: str | None = None,
) -> bool:
    """Update an existing contact. Returns True if any row was updated."""
    conn = _get_conn(db_url)
    now = _now_iso()

    updates: list[str] = []
    params: list[Any] = []

    if name is not None:
        updates.append("name = ?")
        params.append(name)
    if phone is not None:
        updates.append("phone = ?")
        params.append(phone or None)
    if email is not None:
        updates.append("email = ?")
        params.append(email or None)
    if address is not None:
        updates.append("address = ?")
        params.append((address or "").strip() or None)
    if company is not None:
        updates.append("company = ?")
        params.append((company or "").strip() or None)
    if role is not None:
        updates.append("role = ?")
        params.append((role or "").strip() or None)
    if notes is not None:
        updates.append("notes = ?")
        params.append((notes or "").strip())
    if tags is not None:
        clean_tags = [str(t).strip() for t in (tags or []) if str(t).strip()]
        try:
            tags_json = json.dumps(clean_tags)
        except Exception:
            tags_json = "[]"
        updates.append("tags_json = ?")
        params.append(tags_json)
    if favorite is not None:
        try:
            fav = 1 if int(favorite) else 0
        except Exception:
            fav = 0
        updates.append("favorite = ?")
        params.append(fav)
    if relationship is not None:
        updates.append("relationship = ?")
        params.append((relationship or "").strip())
    if source is not None:
        updates.append("source = ?")
        params.append((source or "").strip())

    if not updates:
        return False

    updates.append("updated_at = ?")
    params.append(now)
    params.append(int(contact_id))

    sql = f"UPDATE contacts SET {', '.join(updates)} WHERE id = ?"
    with _db_lock:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        return cur.rowcount > 0


def get_contact_by_phone(
    db_url: str,
    phone: str,
) -> dict[str, Any] | None:
    """Look up a contact by phone number (exact or suffix match).

    Tries exact match first, then falls back to matching on the last
    10 digits to handle +1 / country-code variations.
    """
    conn = _get_conn(db_url)
    raw = (phone or "").strip()
    if not raw:
        return None

    # Exact match first
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM contacts WHERE phone = ? LIMIT 1",
            (raw,),
        ).fetchone()

    if not row:
        # Suffix match – strip to digits and check last 10
        digits = "".join(c for c in raw if c.isdigit())
        suffix = digits[-10:] if len(digits) >= 10 else digits
        if suffix:
            with _db_lock:
                rows = conn.execute(
                    "SELECT * FROM contacts WHERE phone IS NOT NULL",
                ).fetchall()
            for r in rows:
                p = "".join(c for c in (r["phone"] or "") if c.isdigit())
                if p.endswith(suffix):
                    row = r
                    break

    if not row:
        return None
    d = dict(row)
    tags_json = d.pop("tags_json", "[]")
    try:
        d["tags"] = json.loads(tags_json) if tags_json else []
    except Exception:
        d["tags"] = []
    return d


def get_contact_by_id(
    db_url: str,
    contact_id: int,
) -> dict[str, Any] | None:
    """Get a single contact by ID."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM contacts WHERE id = ?",
            (int(contact_id),),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    tags_json = d.pop("tags_json", "[]")
    try:
        d["tags"] = json.loads(tags_json) if tags_json else []
    except Exception:
        d["tags"] = []
    return d


def record_contact_interaction(
    db_url: str,
    contact_id: int,
    channel: str = "unknown",
    direction: str = "inbound",
    summary: str = "",
    ref_id: str = "",
) -> int:
    """Record an interaction with a contact and bump counters."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO contact_interactions
               (contact_id, channel, direction, summary, ref_id,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (int(contact_id), channel, direction, summary, ref_id, now),
        )
        # Bump the interaction_count and last_interaction on the
        # contact itself.
        conn.execute(
            """UPDATE contacts
               SET interaction_count = COALESCE(interaction_count, 0) + 1,
                   last_interaction = ?,
                   updated_at = ?
               WHERE id = ?""",
            (now, now, int(contact_id)),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_contact_interactions(
    db_url: str,
    contact_id: int,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Retrieve recent interactions for a contact."""
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 20)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM contact_interactions "
            "WHERE contact_id = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (int(contact_id), lim),
        ).fetchall()
    return [dict(r) for r in rows]


def get_recent_contacts(
    db_url: str,
    limit: int = 10,
) -> list[dict[str, Any]]:
    """Return contacts with the most recent interactions."""
    conn = _get_conn(db_url)
    lim = max(1, min(50, int(limit or 10)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM contacts "
            "WHERE last_interaction IS NOT NULL "
            "ORDER BY last_interaction DESC LIMIT ?",
            (lim,),
        ).fetchall()
    results: list[dict[str, Any]] = []
    for row in rows:
        d = dict(row)
        tags_json = d.pop("tags_json", "[]")
        try:
            d["tags"] = json.loads(tags_json) if tags_json else []
        except Exception:
            d["tags"] = []
        results.append(d)
    return results


# ---------------------------------------------------------------------------
# Delegation tracking
# ---------------------------------------------------------------------------


def create_delegation(
    db_url: str,
    task_id: int,
    from_agent_id: str,
    to_agent_id: str,
    reason: str = "",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    from_agent_id = canonicalize_assignment_agent(from_agent_id) or "orchestrator"
    to_agent_id = canonicalize_assignment_agent(to_agent_id) or "orchestrator"
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO delegations
               (task_id, from_agent_id, to_agent_id, status, reason,
                created_at)
               VALUES (?, ?, ?, 'active', ?, ?)""",
            (task_id, from_agent_id, to_agent_id, reason, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def complete_delegation(
    db_url: str,
    delegation_id: int,
    result_summary: str = "",
    status: str = "completed",
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """UPDATE delegations
               SET status = ?, result_summary = ?, completed_at = ?
               WHERE id = ?""",
            (status, result_summary, now, delegation_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_delegation(db_url: str, delegation_id: int) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM delegations WHERE id = ?",
            (int(delegation_id),),
        ).fetchone()
    return dict(row) if row is not None else None


def list_delegations_detailed(
    db_url: str,
    status: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """List delegations with joined task metadata for dashboard display."""
    conn = _get_conn(db_url)
    params: list[Any] = []
    where = ""
    if status:
        where = "WHERE d.status = ?"
        params.append(status)
    params.append(int(limit))

    sql = (
        "SELECT d.*, "
        "t.title AS task_title, "
        "t.status AS task_status, "
        "t.priority AS task_priority, "
        "t.assigned_to AS task_assigned_to "
        "FROM delegations d "
        "LEFT JOIN tasks t ON t.id = d.task_id "
        f"{where} "
        "ORDER BY d.created_at DESC LIMIT ?"
    )

    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def list_delegations(
    db_url: str,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    conditions: list[str] = []
    params: list[Any] = []
    if agent_id:
        conditions.append("(from_agent_id = ? OR to_agent_id = ?)")
        params.extend([agent_id, agent_id])
    if status:
        conditions.append("status = ?")
        params.append(status)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    with _db_lock:
        rows = conn.execute(
            f"""SELECT * FROM delegations {where}
                ORDER BY created_at DESC LIMIT ?""",
            params,
        ).fetchall()
    return [dict(row) for row in rows]


# ---------------------------------------------------------------------------
# Agent metrics
# ---------------------------------------------------------------------------


def record_agent_metric(
    db_url: str,
    agent_id: str,
    metric_type: str,
    value: float,
    period: str = "lifetime",
    details: dict[str, Any] | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO agent_metrics
               (agent_id, metric_type, value, period, details_json,
                created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (agent_id, metric_type, value, period, json.dumps(details or {}), now),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_agent_metrics(
    db_url: str,
    agent_id: str,
    metric_type: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    conditions = ["agent_id = ?"]
    params: list[Any] = [agent_id]
    if metric_type:
        conditions.append("metric_type = ?")
        params.append(metric_type)
    where = " AND ".join(conditions)
    params.append(limit)
    with _db_lock:
        rows = conn.execute(
            f"""SELECT * FROM agent_metrics
                WHERE {where}
                ORDER BY created_at DESC LIMIT ?""",
            params,
        ).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["details"] = json.loads(d.pop("details_json", "{}"))
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Evolution log
# ---------------------------------------------------------------------------


# Directories whose contents are vendored or generated: a proposal that edits them either gets
# overwritten by the next install or is not source anyone maintains. Measured 2026-09-15: 19
# evolution_log rows targeted web/node_modules/flatted/python/flatted.py.
_VENDORED_PATH_PARTS = frozenset(
    {"node_modules", ".venv", "site-packages", "__pycache__", ".next", "dist", "build", ".git"}
)


_EVOLUTION_COLUMNS_ENSURED: set[str] = set()


def _ensure_evolution_columns(db_url: str, conn) -> None:
    """Add status / status_note to evolution_log if absent (lazy, idempotent, per db_url).

    `applied` alone cannot express "reviewed and rejected", which is why 56 dead offers sat in the
    review queue with no way out. `status` is 'open' for a proposal awaiting a decision, 'applied' or
    'dismissed' once it has had one; `status_note` says why, and is never a rewrite of history.
    """
    if db_url in _EVOLUTION_COLUMNS_ENSURED:
        return
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(evolution_log)")}
    except Exception:  # noqa: BLE001 - a missing table is not this function's problem
        return
    if not cols:
        return
    if "status" not in cols:
        conn.execute("ALTER TABLE evolution_log ADD COLUMN status TEXT")
        conn.execute(
            "UPDATE evolution_log SET status = CASE WHEN applied = 1 THEN 'applied' else 'open' END "
            "WHERE status IS NULL"
        )
    if "status_note" not in cols:
        conn.execute("ALTER TABLE evolution_log ADD COLUMN status_note TEXT")
    conn.commit()
    _EVOLUTION_COLUMNS_ENSURED.add(db_url)


def dismiss_dead_evolution_proposals(db_url: str) -> dict[str, int]:
    """Dismiss unapplied offers that can never be acted on, and say why on each row.

    Two classes, both measured on 2026-09-15:

    * a target inside a vendored or generated tree (19 rows all-time, 18 of them unapplied) -- the
      writer now refuses to record these at all, so the surviving rows are history;
    * a duplicate of a newer offer on the same target with the same description (38 rows on one file)
      -- the writer now dedups these, so the older copies are superseded by the newest.

    Only `held`-equivalent rows (`status='open'`) are touched; nothing is deleted and the newest copy of
    each duplicate set stays open.
    """
    conn = _get_conn(db_url)
    _ensure_evolution_columns(db_url, conn)
    counts = {"vendored": 0, "superseded": 0}
    with _db_lock:
        rows = conn.execute(
            # Newest first, so the row the drain keeps for a duplicate set is the newest one --
            # without the ORDER BY it kept the first by id (the oldest) and dismissed the rest.
            "SELECT id, files_changed, change_type, description FROM evolution_log "
            "WHERE applied = 0 AND COALESCE(status, 'open') = 'open' "
            "ORDER BY created_at DESC, id DESC"
        ).fetchall()
        keep: dict[tuple, int] = {}
        for row in rows:
            try:
                import json as _json

                first = (_json.loads(row["files_changed"] or "[]") or [""])[0]
            except Exception:  # noqa: BLE001
                first = ""
            if _is_vendored_path(str(first)):
                conn.execute(
                    "UPDATE evolution_log SET status = 'dismissed', status_note = ? WHERE id = ?",
                    ("dismissed: target is vendored/generated; the writer refuses this class now", row["id"]),
                )
                counts["vendored"] += 1
                continue
            key = (row["change_type"], row["files_changed"], row["description"])
            if key in keep:
                conn.execute(
                    "UPDATE evolution_log SET status = 'dismissed', status_note = ? WHERE id = ?",
                    ("dismissed: superseded by a newer identical offer", row["id"]),
                )
                counts["superseded"] += 1
            else:
                keep[key] = int(row["id"])
        conn.commit()
    return counts


def _is_vendored_path(path: str) -> bool:
    """True when a path lives inside a vendored or generated tree."""
    norm = str(path or "").replace("\\", "/").strip().lstrip("./").lower()
    if not norm:
        return True
    return any(part in _VENDORED_PATH_PARTS for part in norm.split("/") if part)


def log_evolution(
    db_url: str,
    change_type: str,
    description: str,
    files_changed: list[str] | None = None,
    proposal_id: str | None = None,
    applied: bool = False,
    agent_id: str = "orchestrator",
) -> int:
    """Record an evolution offer, once, and never against a vendored file.

    Two guards, both measured on 2026-09-15 (see the module note in the commit and P4):

    * vendored/generated targets are dropped from the list -- an offer that still has a real source
      file keeps it, and an offer with nothing left is not recorded at all (returns 0);
    * an identical UNapplied offer is not recorded twice. The engine mints a fresh `proposal_id` each
      time it re-offers a change, so the key is `(change_type, files_changed, description)` while
      `applied=0`: 38 unapplied rows for one file shared one description across 38 proposal ids.
      An application always inserts -- that is a fact, not an offer.
    """
    conn = _get_conn(db_url)
    now = _now_iso()
    _ensure_evolution_columns(db_url, conn)

    targets = [str(p) for p in (files_changed or [])]
    kept = [p for p in targets if not _is_vendored_path(p)]
    dropped = [p for p in targets if _is_vendored_path(p)]
    if dropped:
        _log.info(
            "evolution: dropped %d vendored/generated target(s) from a proposal: %s",
            len(dropped),
            ", ".join(dropped[:4]),
        )
    if targets and not kept:
        _log.info("evolution: proposal targets only vendored/generated files; not logged")
        return 0
    payload = json.dumps(kept)

    with _db_lock:
        if not applied:
            existing = conn.execute(
                """SELECT id FROM evolution_log
                   WHERE applied = 0 AND change_type = ? AND files_changed = ? AND description = ?
                   ORDER BY id LIMIT 1""",
                (change_type, payload, description),
            ).fetchone()
            if existing is not None:
                return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO evolution_log
               (agent_id, change_type, description, files_changed,
                proposal_id, applied, created_at, status, status_note)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                change_type,
                description,
                payload,
                proposal_id,
                1 if applied else 0,
                now,
                "applied" if applied else "open",
                None,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_evolution_history(
    db_url: str,
    agent_id: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    if agent_id:
        sql = """SELECT * FROM evolution_log
                 WHERE agent_id = ?
                 ORDER BY created_at DESC LIMIT ?"""
        params: tuple = (agent_id, limit)
    else:
        sql = """SELECT * FROM evolution_log
                 ORDER BY created_at DESC LIMIT ?"""
        params = (limit,)
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for row in rows:
        d = dict(row)
        d["files_changed"] = json.loads(d.get("files_changed") or "[]")
        result.append(d)
    return result


# ---------------------------------------------------------------------------
# Evolution changelog (Round 2 A1.C — trust + recover + remember)
# ---------------------------------------------------------------------------


def record_evolution_changelog(
    db_url: str,
    *,
    file_path: str,
    change_summary: str,
    reasoning: str = "",
    before_excerpt: str = "",
    after_excerpt: str = "",
    proposal_id: str | None = None,
    agent_id: str = "orchestrator",
    commit_sha: str | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO evolution_changelog
               (proposal_id, agent_id, file_path, change_summary,
                reasoning, before_excerpt, after_excerpt,
                commit_sha, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                proposal_id,
                agent_id,
                file_path,
                change_summary,
                reasoning,
                before_excerpt,
                after_excerpt,
                commit_sha,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def mark_evolution_rolled_back(
    db_url: str,
    changelog_id: int,
    *,
    reason: str,
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """UPDATE evolution_changelog
               SET rolled_back = 1,
                   rollback_reason = ?,
                   rolled_back_at = ?
               WHERE id = ? AND rolled_back = 0""",
            (reason, now, changelog_id),
        )
        conn.commit()
        return cur.rowcount > 0


def list_evolution_changelog(
    db_url: str,
    *,
    limit: int = 50,
    file_path: str | None = None,
    rolled_back_only: bool = False,
    since: str | None = None,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    clauses: list[str] = []
    params: list[Any] = []
    if file_path:
        clauses.append("file_path = ?")
        params.append(file_path)
    if rolled_back_only:
        clauses.append("rolled_back = 1")
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = (
        "SELECT * FROM evolution_changelog"
        + where
        + " ORDER BY created_at DESC LIMIT ?"
    )
    params.append(int(limit))
    with _db_lock:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# VP inbox (Round 2 B1) — persistent queue between VP sessions
# ---------------------------------------------------------------------------


def vp_inbox_add(
    db_url: str,
    *,
    source: str,
    kind: str,
    title: str,
    body: str = "",
    priority: str = "normal",
    ref_type: str | None = None,
    ref_id: str | None = None,
) -> int:
    """Add an item to the VP inbox.

    Called by CoS, evolution, healing, agents, etc. while VP is offline.
    """
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO vp_inbox
               (source, kind, priority, title, body,
                ref_type, ref_id, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?)""",
            (
                source,
                kind,
                priority,
                title,
                body,
                ref_type,
                ref_id,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def vp_inbox_list(
    db_url: str,
    *,
    status: str | None = "open",
    priority: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    clauses: list[str] = []
    params: list[Any] = []
    if status:
        clauses.append("status = ?")
        params.append(status)
    if priority:
        clauses.append("priority = ?")
        params.append(priority)
    where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
    priority_order = (
        " ORDER BY CASE priority "
        "WHEN 'p0' THEN 0 WHEN 'p1' THEN 1 "
        "WHEN 'p2' THEN 2 WHEN 'p3' THEN 3 "
        "WHEN 'normal' THEN 4 ELSE 5 END, "
        "created_at DESC"
    )
    sql = "SELECT * FROM vp_inbox" + where + priority_order + " LIMIT ?"
    params.append(int(limit))
    with _db_lock:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [dict(r) for r in rows]


def vp_inbox_count(
    db_url: str,
    *,
    status: str = "open",
) -> dict[str, int]:
    """Return counts by priority for inbox items in the given status."""
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT priority, COUNT(*) AS c
               FROM vp_inbox WHERE status = ?
               GROUP BY priority""",
            (status,),
        ).fetchall()
    return {str(r["priority"]): int(r["c"]) for r in rows}


def vp_inbox_mark_read(db_url: str, inbox_id: int) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """UPDATE vp_inbox
               SET status = 'read', read_at = ?
               WHERE id = ? AND status = 'open'""",
            (now, inbox_id),
        )
        conn.commit()
        return cur.rowcount > 0


def vp_inbox_resolve(
    db_url: str,
    inbox_id: int,
    *,
    note: str = "",
    dismiss: bool = False,
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    new_status = "dismissed" if dismiss else "resolved"
    with _db_lock:
        cur = conn.execute(
            """UPDATE vp_inbox
               SET status = ?, resolved_at = ?, resolution_note = ?
               WHERE id = ? AND status IN ('open', 'read')""",
            (new_status, now, note, inbox_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Stats / overview
# ---------------------------------------------------------------------------


def db_stats(db_url: str) -> dict[str, Any]:
    conn = _get_conn(db_url)
    with _db_lock:
        conv_count = conn.execute("SELECT COUNT(*) as c FROM conversations").fetchone()[
            "c"
        ]
        mem_count = conn.execute("SELECT COUNT(*) as c FROM memories").fetchone()["c"]
        knowledge_count = conn.execute(
            "SELECT COUNT(*) as c FROM knowledge"
        ).fetchone()["c"]
        cred_count = conn.execute("SELECT COUNT(*) as c FROM credentials").fetchone()[
            "c"
        ]
        activity_count = conn.execute(
            "SELECT COUNT(*) as c FROM activity_log"
        ).fetchone()["c"]
    task_summary = get_task_status_summary(db_url)
    return {
        "conversations": conv_count,
        "memories": mem_count,
        "tasks": task_summary["by_status"],
        "tasks_completed_total": task_summary["completed_total"],
        "tasks_active_total": task_summary["active_total"],
        "knowledge_entries": knowledge_count,
        "credentials": cred_count,
        "activity_log_entries": activity_count,
    }


# ---------------------------------------------------------------------------
# SMS log persistence
# ---------------------------------------------------------------------------


def log_sms(
    db_url: str,
    twilio_sid: str | None,
    direction: str,
    from_number: str,
    to_number: str,
    body: str,
    status: str,
    template_id: str | None = None,
    error_message: str | None = None,
    agent_id: str = "orchestrator",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    ca = created_at or now
    ua = updated_at or ca
    # Redact at the write: every sms_log writer in the app funnels through this
    # function, log_inbound_sms_once or log_sms_best_effort.  The customer's own
    # text is what carries the PAN; the row keeps the last four for matching.
    body = redact_body_for_storage(body)
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO sms_log
               (twilio_sid, direction, from_number, to_number, body,
                template_id, status, error_message, agent_id,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                twilio_sid,
                direction,
                from_number,
                to_number,
                body,
                template_id,
                status,
                error_message,
                agent_id,
                ca,
                ua,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def log_inbound_sms_once(
    db_url: str,
    twilio_sid: str | None,
    from_number: str,
    to_number: str,
    body: str,
    *,
    status: str = "received",
    created_at: str | None = None,
    agent_id: str = "orchestrator",
    max_attempts: int = 6,
    max_seconds: float = 5.0,
) -> int | None:
    """Insert one inbound SMS exactly once, retrying transient SQLITE_BUSY.

    Idempotent on ``(direction='inbound', twilio_sid)`` when a sid is present,
    so the durable spool in :mod:`app.services.sms_spool` can safely re-run a
    payload after a partial failure.  The retry is bounded (``max_attempts`` and
    ``max_seconds``) so an inbound webhook can never hang on the write lock.
    Returns the row id (new or pre-existing) or raises the last OperationalError
    if the lock cannot be taken inside the budget.
    """
    sid = str(twilio_sid or "").strip()
    ca = created_at or _now_iso()
    # Redact at the write.  The durable spool already redacted its copy (see
    # app.services.sms_spool.enqueue_inbound); this covers the direct path and
    # anything that reaches the helper another way.
    body = redact_body_for_storage(body)
    deadline = time.monotonic() + max(0.0, max_seconds)
    delay = 0.05
    last_exc: BaseException | None = None

    for attempt in range(1, max(1, max_attempts) + 1):
        conn = _get_conn(db_url)
        retry_needed = False
        with _db_lock:
            try:
                # Never inherit a half-open transaction from a prior attempt.
                if conn.in_transaction:
                    conn.rollback()
                if sid:
                    existing = conn.execute(
                        "SELECT id FROM sms_log "
                        "WHERE direction = 'inbound' AND twilio_sid = ? "
                        "LIMIT 1",
                        (sid,),
                    ).fetchone()
                    if existing is not None:
                        return int(existing[0])
                cur = conn.execute(
                    """INSERT INTO sms_log
                       (twilio_sid, direction, from_number, to_number, body,
                        template_id, status, error_message, agent_id,
                        created_at, updated_at)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        sid or None,
                        "inbound",
                        from_number,
                        to_number,
                        body,
                        None,
                        status,
                        None,
                        agent_id,
                        ca,
                        ca,
                    ),
                )
                commit_retry(conn, attempts=4, base_delay=0.05)
                return cur.lastrowid  # type: ignore[return-value]
            except sqlite3.OperationalError as exc:
                last_exc = exc
                try:
                    conn.rollback()
                except Exception:
                    pass
                if (
                    not is_locked_error(exc)
                    or attempt >= max_attempts
                    or time.monotonic() >= deadline
                ):
                    raise
                retry_needed = True
        if retry_needed:
            time.sleep(delay)
            delay = min(delay * 2, 0.5)
    if last_exc is not None:
        raise last_exc
    return None


def log_sms_best_effort(
    db_url: str,
    twilio_sid: str | None,
    direction: str,
    from_number: str,
    to_number: str,
    body: str,
    status: str,
    template_id: str | None = None,
    error_message: str | None = None,
    agent_id: str = "orchestrator",
    created_at: str | None = None,
    updated_at: str | None = None,
) -> int | None:
    """Insert an sms_log row without ever raising a transient lock error.

    Same INSERT as :func:`log_sms`.  The connection's ``busy_timeout`` (10 s) is
    the bounded wait; if the write lock is still not free afterwards, the failed
    transaction is rolled back and this returns ``None`` with a warning instead
    of propagating.  Used by the Twilio webhook for the outbound-reply audit
    row: Twilio does not retry an inbound SMS after a 5xx, and the inbound text
    is already durable in the filesystem spool, so dropping this audit row is
    strictly better than answering the customer with a 500.
    """
    now = _now_iso()
    ca = created_at or now
    ua = updated_at or ca
    conn = _get_conn(db_url)
    # Redact at the write: this is the Twilio reply's audit row, and the inbound
    # text it quotes is the customer's own words.
    body = redact_body_for_storage(body)
    with _db_lock:
        try:
            # Never inherit a half-open transaction from a prior failed write;
            # replaying the INSERT inside it would duplicate the row.
            if conn.in_transaction:
                conn.rollback()
            cur = conn.execute(
                """INSERT INTO sms_log
                   (twilio_sid, direction, from_number, to_number, body,
                    template_id, status, error_message, agent_id,
                    created_at, updated_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    twilio_sid,
                    direction,
                    from_number,
                    to_number,
                    body,
                    template_id,
                    status,
                    error_message,
                    agent_id,
                    ca,
                    ua,
                ),
            )
            commit_retry(conn, attempts=2, base_delay=0.05)
            return cur.lastrowid  # type: ignore[return-value]
        except sqlite3.OperationalError as exc:
            if not is_locked_error(exc):
                raise
            try:
                conn.rollback()
            except Exception:
                pass
            _log.warning(
                "sms_log row not written (SQLite busy; audit row skipped): %s",
                exc,
            )
            return None


def update_sms_status(
    db_url: str,
    twilio_sid: str,
    status: str,
    error_message: str | None = None,
) -> None:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """UPDATE sms_log
               SET status = ?, error_message = ?, updated_at = ?
               WHERE twilio_sid = ?""",
            (status, error_message, now, twilio_sid),
        )
        conn.commit()


#: Twilio statuses after which a message's fate will not change again. Anything
#: outside this set is still in flight and is what a reconciliation pass looks
#: at; `sent` is deliberately NOT terminal -- Twilio emits `sent` when the
#: message leaves Twilio and `delivered`/`undelivered` later, so a row sitting at
#: `sent` is exactly the row that can be lying about delivery.
SMS_TERMINAL_STATUSES = ("delivered", "undelivered", "failed", "canceled", "read")


def list_sms_log_unresolved(
    db_url: str,
    *,
    limit: int = 200,
    direction: str = "outbound",
    include_terminal: bool = False,
) -> list[dict[str, Any]]:
    """Outbound rows whose delivery verdict is not yet known.

    The input to status reconciliation (``scripts/reconcile-sms-status.py``).
    Only rows carrying a ``twilio_sid`` can be asked about -- without one there
    is nothing to look up, and a row with no sid is itself a finding.

    ``sent`` counts as unresolved on purpose: it means "Twilio accepted it", not
    "it arrived", and 15 rows in the live table sat at ``sent`` while Twilio's
    own record said ``undelivered`` with a carrier error.
    """
    conn = _get_conn(db_url)
    query = "SELECT * FROM sms_log WHERE direction = ? AND twilio_sid IS NOT NULL AND twilio_sid != ''"
    params: list[Any] = [direction]
    if not include_terminal:
        placeholders = ", ".join("?" for _ in SMS_TERMINAL_STATUSES)
        query += f" AND status NOT IN ({placeholders})"
        params.extend(SMS_TERMINAL_STATUSES)
    query += " ORDER BY id DESC LIMIT ?"
    params.append(max(1, int(limit)))
    with _db_lock:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def list_sms_log(
    db_url: str,
    limit: int = 50,
    to_number: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    query = "SELECT * FROM sms_log WHERE 1=1"
    params: list[Any] = []
    if to_number:
        query += " AND to_number = ?"
        params.append(to_number)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _db_lock:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_sms_conversation(
    db_url: str,
    phone_number: str,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """Get recent SMS conversation with a specific phone number.

    Returns messages both TO and FROM the given number, ordered
    oldest-first so they can be used as chat history.
    """
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            """SELECT direction, from_number, to_number, body, created_at
               FROM sms_log
               WHERE (from_number = ? OR to_number = ?)
                 AND COALESCE(status, '') != 'suppressed'
               ORDER BY created_at DESC
               LIMIT ?""",
            (phone_number, phone_number, limit),
        ).fetchall()
    # Reverse so oldest comes first (chronological order for chat context)
    return [dict(r) for r in reversed(rows)]


def list_sms_threads(
    db_url: str,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return SMS threads grouped by phone number with latest message preview.

    Each thread has: phone, last_body, last_direction, last_at, msg_count.
    """
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            """
            SELECT
              phone,
              body AS last_body,
              direction AS last_direction,
              created_at AS last_at,
              cnt AS msg_count
            FROM (
              SELECT
                CASE WHEN direction='inbound' THEN from_number ELSE to_number END AS phone,
                body, direction, created_at,
                COUNT(*) OVER (PARTITION BY
                  CASE WHEN direction='inbound' THEN from_number ELSE to_number END
                ) AS cnt,
                ROW_NUMBER() OVER (PARTITION BY
                  CASE WHEN direction='inbound' THEN from_number ELSE to_number END
                  ORDER BY created_at DESC
                ) AS rn
              FROM sms_log
            ) sub
            WHERE rn = 1
            ORDER BY last_at DESC
            LIMIT ?
            """,
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Voice notes log persistence
# ---------------------------------------------------------------------------


def log_voice_note(
    db_url: str,
    recipient_name: str | None,
    recipient_phone: str,
    text_content: str,
    voice: str = "alloy",
    twilio_sid: str | None = None,
    audio_filename: str | None = None,
    audio_url: str | None = None,
    duration_sec: int | None = None,
    file_bytes: int = 0,
    status: str = "created",
    error_message: str | None = None,
    agent_id: str = "orchestrator",
    created_at: str | None = None,
    sent_at: str | None = None,
) -> int:
    """Record a voice note send in the voice_notes table."""
    conn = _get_conn(db_url)
    now = _now_iso()
    ca = created_at or now
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO voice_notes
               (twilio_sid, recipient_name, recipient_phone, text_content,
                voice, audio_filename, audio_url, duration_sec, file_bytes,
                status, error_message, agent_id, created_at, sent_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                twilio_sid,
                recipient_name,
                recipient_phone,
                text_content,
                voice,
                audio_filename,
                audio_url,
                duration_sec,
                file_bytes,
                status,
                error_message,
                agent_id,
                ca,
                sent_at,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def update_voice_note_status(
    db_url: str,
    note_id: int,
    status: str,
    twilio_sid: str | None = None,
    error_message: str | None = None,
    sent_at: str | None = None,
) -> None:
    """Update the status of a voice note after send attempt."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        sets = ["status = ?", "error_message = ?"]
        params: list[Any] = [status, error_message]
        if twilio_sid is not None:
            sets.append("twilio_sid = ?")
            params.append(twilio_sid)
        if sent_at is not None:
            sets.append("sent_at = ?")
            params.append(sent_at)
        params.append(now)
        params.append(note_id)
        conn.execute(
            f"UPDATE voice_notes SET {', '.join(sets)}, updated_at = ? WHERE id = ?",
            params,
        )
        conn.commit()


def list_voice_notes(
    db_url: str,
    limit: int = 50,
    recipient_phone: str | None = None,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List voice notes, newest first."""
    conn = _get_conn(db_url)
    query = "SELECT * FROM voice_notes WHERE 1=1"
    params: list[Any] = []
    if recipient_phone:
        query += " AND recipient_phone = ?"
        params.append(recipient_phone)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _db_lock:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def get_voice_note_stats(db_url: str) -> dict[str, Any]:
    """Get aggregate stats about voice notes."""
    conn = _get_conn(db_url)
    with _db_lock:
        total = conn.execute("SELECT COUNT(*) FROM voice_notes").fetchone()[0]
        sent = conn.execute(
            "SELECT COUNT(*) FROM voice_notes WHERE status = 'sent'"
        ).fetchone()[0]
        failed = conn.execute(
            "SELECT COUNT(*) FROM voice_notes WHERE status = 'failed'"
        ).fetchone()[0]
        total_bytes = conn.execute(
            "SELECT COALESCE(SUM(file_bytes), 0) FROM voice_notes"
        ).fetchone()[0]
        by_recipient = conn.execute(
            """SELECT recipient_name, recipient_phone, COUNT(*) as count
               FROM voice_notes
               GROUP BY recipient_phone
               ORDER BY count DESC
               LIMIT 20"""
        ).fetchall()
    return {
        "total": total,
        "sent": sent,
        "failed": failed,
        "total_bytes": total_bytes,
        "by_recipient": [dict(r) for r in by_recipient],
    }


def list_call_log_enriched(
    db_url: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return call log enriched with contact names, transcripts, and recordings."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM call_log ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
        calls = [dict(r) for r in rows]

        for call in calls:
            cs = call.get("call_sid") or ""
            # Attach transcript
            tr = conn.execute(
                "SELECT transcript_text, source FROM voice_transcripts "
                "WHERE call_sid = ? ORDER BY created_at DESC LIMIT 1",
                (cs,),
            ).fetchone()
            call["transcript"] = dict(tr)["transcript_text"] if tr else None
            call["transcript_source"] = dict(tr)["source"] if tr else None

            # Attach recording filename
            rec = conn.execute(
                "SELECT local_filename, duration_sec FROM voice_recordings "
                "WHERE call_sid = ? ORDER BY created_at DESC LIMIT 1",
                (cs,),
            ).fetchone()
            call["recording_filename"] = dict(rec)["local_filename"] if rec else None
            call["recording_duration"] = dict(rec)["duration_sec"] if rec else None

            # Attach contact name
            other = (
                call.get("from_number")
                if call.get("direction") == "inbound"
                else call.get("to_number")
            )
            if other:
                ct = conn.execute(
                    "SELECT name FROM contacts WHERE phone = ? LIMIT 1",
                    (other,),
                ).fetchone()
                call["contact_name"] = dict(ct)["name"] if ct else None
            else:
                call["contact_name"] = None

    return calls


def log_sms_media(
    db_url: str,
    *,
    message_sid: str | None,
    direction: str = "inbound",
    from_number: str | None = None,
    to_number: str | None = None,
    media_index: int = 0,
    content_type: str | None = None,
    source_url: str | None = None,
    local_filename: str | None = None,
    file_bytes: int | None = None,
    vision_summary: str | None = None,
    status: str = "saved",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO sms_media
               (message_sid, direction, from_number, to_number,
                media_index, content_type, source_url, local_filename,
                file_bytes, vision_summary, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                (str(message_sid).strip() if message_sid else None),
                str(direction or "inbound"),
                (str(from_number).strip() if from_number else None),
                (str(to_number).strip() if to_number else None),
                int(media_index or 0),
                (str(content_type).strip() if content_type else None),
                (str(source_url).strip() if source_url else None),
                (str(local_filename).strip() if local_filename else None),
                int(file_bytes or 0),
                (str(vision_summary).strip() if vision_summary else None),
                str(status or "saved"),
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_sms_media_for_message(
    db_url: str,
    *,
    message_sid: str,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    sid = str(message_sid or "").strip()
    if not sid:
        return []
    with _db_lock:
        rows = conn.execute(
            (
                "SELECT * FROM sms_media WHERE message_sid = ? "
                "ORDER BY media_index ASC"
            ),
            (sid,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Voice recordings
# ---------------------------------------------------------------------------


def log_voice_recording(
    db_url: str,
    *,
    from_number: str,
    to_number: str,
    call_sid: str | None = None,
    recording_sid: str | None = None,
    duration_sec: int | None = None,
    source_url: str | None = None,
    local_filename: str | None = None,
    status: str = "saved",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO voice_recordings
               (call_sid, recording_sid, from_number, to_number,
                duration_sec, source_url, local_filename, status, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                call_sid,
                recording_sid,
                from_number,
                to_number,
                int(duration_sec or 0),
                source_url,
                local_filename,
                (status or "saved"),
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_voice_recordings(
    db_url: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM voice_recordings ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Call log + transcripts
# ---------------------------------------------------------------------------


def upsert_call_log(
    db_url: str,
    *,
    call_sid: str,
    direction: str,
    from_number: str,
    to_number: str,
    status: str = "unknown",
    duration_sec: int | None = None,
    recording_url: str | None = None,
    recording_sid: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    """Insert/update a call log row keyed by call_sid."""
    sid = str(call_sid or "").strip()
    if not sid:
        return False

    conn = _get_conn(db_url)
    now = _now_iso()

    meta_json = "{}"
    if metadata is not None:
        try:
            meta_json = json.dumps(metadata, ensure_ascii=False, default=str)[:4000]
        except Exception:
            meta_json = json.dumps({"metadata": str(metadata)})[:4000]

    dur = int(duration_sec) if duration_sec is not None else None

    with _db_lock:
        conn.execute(
            """INSERT INTO call_log
               (call_sid, direction, from_number, to_number, status,
                duration_sec, recording_url, recording_sid, metadata_json,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(call_sid) DO UPDATE
               SET direction = excluded.direction,
                   from_number = excluded.from_number,
                   to_number = excluded.to_number,
                   status = excluded.status,
                   duration_sec = COALESCE(excluded.duration_sec, call_log.duration_sec),
                   recording_url = COALESCE(excluded.recording_url, call_log.recording_url),
                   recording_sid = COALESCE(excluded.recording_sid, call_log.recording_sid),
                   metadata_json = CASE
                       WHEN excluded.metadata_json != '{}' THEN excluded.metadata_json
                       ELSE call_log.metadata_json
                   END,
                   updated_at = excluded.updated_at
            """,
            (
                sid,
                str(direction or "unknown"),
                str(from_number or "unknown"),
                str(to_number or "unknown"),
                str(status or "unknown"),
                dur,
                recording_url,
                recording_sid,
                meta_json,
                now,
                now,
            ),
        )
        conn.commit()
    return True


def get_call_log_by_sid(
    db_url: str,
    call_sid: str,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    sid = str(call_sid or "").strip()
    if not sid:
        return None
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM call_log WHERE call_sid = ?",
            (sid,),
        ).fetchone()
    return dict(row) if row else None


def _voice_handoff_row_to_dict(
    row: sqlite3.Row | dict[str, Any] | None,
    *,
    include_secret: bool = False,
) -> dict[str, Any] | None:
    if row is None:
        return None
    data = dict(row)
    try:
        data["owner_notified"] = bool(int(data.get("owner_notified") or 0))
    except Exception:
        data["owner_notified"] = bool(data.get("owner_notified"))
    try:
        data["poll_count"] = int(data.get("poll_count") or 0)
    except Exception:
        data["poll_count"] = 0
    try:
        expires_at = data.get("expires_at")
        data["expires_at"] = float(expires_at) if expires_at is not None else None
    except Exception:
        data["expires_at"] = None
    if not include_secret:
        data.pop("decision_token", None)
    return data


def create_voice_handoff_request(
    db_url: str,
    *,
    request_id: str,
    call_sid: str,
    from_number: str,
    to_number: str,
    relationship: str,
    caller_name: str,
    reason: str,
    status: str = "pending",
    owner_notified: bool = False,
    poll_count: int = 0,
    owner_phone: str = "",
    decision_token: str | None = None,
    decided_by: str | None = None,
    decided_at: str | None = None,
    expires_at: float | None = None,
    created_at: str | None = None,
    updated_at: str | None = None,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    now = _now_iso()
    created = str(created_at or now)
    updated = str(updated_at or created)
    with _db_lock:
        conn.execute(
            """INSERT INTO voice_handoff_requests
               (request_id, call_sid, from_number, to_number, relationship,
                caller_name, reason, status, owner_notified, poll_count,
                owner_phone, decision_token, decided_by, decided_at, expires_at,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(request_id or "").strip(),
                str(call_sid or "").strip(),
                str(from_number or "").strip(),
                str(to_number or "").strip(),
                str(relationship or "unknown").strip(),
                str(caller_name or "").strip(),
                str(reason or "").strip(),
                str(status or "pending").strip(),
                1 if owner_notified else 0,
                int(poll_count or 0),
                str(owner_phone or "").strip(),
                str(decision_token or "").strip() or None,
                str(decided_by or "").strip() or None,
                str(decided_at or "").strip() or None,
                float(expires_at) if expires_at is not None else None,
                created,
                updated,
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM voice_handoff_requests WHERE request_id = ?",
            (str(request_id or "").strip(),),
        ).fetchone()
    return _voice_handoff_row_to_dict(row, include_secret=True)


def get_voice_handoff_request(
    db_url: str,
    request_id: str,
    *,
    include_secret: bool = False,
) -> dict[str, Any] | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM voice_handoff_requests WHERE request_id = ?",
            (rid,),
        ).fetchone()
    return _voice_handoff_row_to_dict(row, include_secret=include_secret)


def get_voice_handoff_request_for_call(
    db_url: str,
    call_sid: str,
    *,
    status: str | None = None,
    include_secret: bool = False,
) -> dict[str, Any] | None:
    sid = str(call_sid or "").strip()
    if not sid:
        return None
    conn = _get_conn(db_url)
    sql = (
        "SELECT * FROM voice_handoff_requests WHERE call_sid = ?"
        + (" AND status = ?" if status else "")
        + " ORDER BY created_at DESC LIMIT 1"
    )
    params: tuple[Any, ...] = (sid, status) if status else (sid,)
    with _db_lock:
        row = conn.execute(sql, params).fetchone()
    return _voice_handoff_row_to_dict(row, include_secret=include_secret)


def list_voice_handoff_requests(
    db_url: str,
    *,
    status: str | None = None,
    limit: int = 20,
    include_secret: bool = False,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(100, int(limit or 20)))
    sql = "SELECT * FROM voice_handoff_requests"
    params: list[Any] = []
    if status:
        sql += " WHERE status = ?"
        params.append(str(status or "").strip())
    sql += " ORDER BY updated_at DESC LIMIT ?"
    params.append(lim)
    with _db_lock:
        rows = conn.execute(sql, tuple(params)).fetchall()
    return [
        _voice_handoff_row_to_dict(row, include_secret=include_secret) or {}
        for row in rows
    ]


def update_voice_handoff_request(
    db_url: str,
    request_id: str,
    **updates_in: Any,
) -> dict[str, Any] | None:
    rid = str(request_id or "").strip()
    if not rid:
        return None

    updates: list[str] = []
    params: list[Any] = []
    for key in (
        "call_sid",
        "from_number",
        "to_number",
        "relationship",
        "caller_name",
        "reason",
        "status",
        "owner_phone",
        "decision_token",
        "decided_by",
        "decided_at",
    ):
        if key in updates_in:
            updates.append(f"{key} = ?")
            params.append(str(updates_in.get(key) or "").strip() or None)
    if "owner_notified" in updates_in:
        updates.append("owner_notified = ?")
        params.append(1 if updates_in.get("owner_notified") else 0)
    if "poll_count" in updates_in:
        try:
            poll_count = int(updates_in.get("poll_count") or 0)
        except Exception:
            poll_count = 0
        updates.append("poll_count = ?")
        params.append(poll_count)
    if "expires_at" in updates_in:
        expires_at = updates_in.get("expires_at")
        updates.append("expires_at = ?")
        params.append(float(expires_at) if expires_at is not None else None)
    if not updates:
        return get_voice_handoff_request(db_url, rid, include_secret=True)

    updates.append("updated_at = ?")
    params.append(_now_iso())
    params.append(rid)

    conn = _get_conn(db_url)
    sql = f"UPDATE voice_handoff_requests SET {', '.join(updates)} WHERE request_id = ?"
    with _db_lock:
        cur = conn.execute(sql, tuple(params))
        conn.commit()
        if cur.rowcount <= 0:
            return None
        row = conn.execute(
            "SELECT * FROM voice_handoff_requests WHERE request_id = ?",
            (rid,),
        ).fetchone()
    return _voice_handoff_row_to_dict(row, include_secret=True)


def expire_voice_handoff_requests(
    db_url: str,
    *,
    now_ts: float | None = None,
) -> int:
    current = float(now_ts if now_ts is not None else time.time())
    conn = _get_conn(db_url)
    now_iso = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """UPDATE voice_handoff_requests
               SET status = 'expired', updated_at = ?
               WHERE status = 'pending'
                 AND expires_at IS NOT NULL
                 AND expires_at <= ?""",
            (now_iso, current),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def list_call_log(
    db_url: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM call_log ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


def save_voice_transcript(
    db_url: str,
    *,
    call_sid: str | None,
    recording_sid: str | None,
    transcript_text: str,
    source: str = "unknown",
) -> int:
    """Best-effort transcript persistence.

    This uses insert-with-dedup (not a strict upsert) to avoid relying on
    optional uniqueness constraints.
    """
    txt = str(transcript_text or "").strip()
    if not txt:
        return 0

    cs = str(call_sid or "").strip() or None
    rs = str(recording_sid or "").strip() or None
    conn = _get_conn(db_url)
    now = _now_iso()

    with _db_lock:
        # Dedup if we have a recording_sid; otherwise dedup by call_sid.
        if rs:
            conn.execute(
                "DELETE FROM voice_transcripts WHERE recording_sid = ?",
                (rs,),
            )
        elif cs:
            conn.execute(
                "DELETE FROM voice_transcripts WHERE call_sid = ?",
                (cs,),
            )

        cur = conn.execute(
            """INSERT INTO voice_transcripts
               (call_sid, recording_sid, transcript_text, source, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (cs, rs, txt, str(source or "unknown"), now, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_voice_transcript_for_call(
    db_url: str,
    *,
    call_sid: str,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    sid = str(call_sid or "").strip()
    if not sid:
        return None
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM voice_transcripts WHERE call_sid = ? ORDER BY created_at DESC LIMIT 1",
            (sid,),
        ).fetchone()
    return dict(row) if row else None


def log_delegation_execution(
    db_url: str,
    *,
    event_type: str,
    target_type: str,
    target_id: int | None,
    request: Any,
    response: Any,
    ok: bool,
    error_message: str | None = None,
) -> int:
    """Persist a single external execution attempt."""
    conn = _get_conn(db_url)
    now = _now_iso()
    try:
        req_json = json.dumps(request, ensure_ascii=False, default=str)[:4000]
    except Exception:
        req_json = json.dumps({"request": str(request)})[:4000]
    try:
        resp_json = json.dumps(response, ensure_ascii=False, default=str)[:4000]
    except Exception:
        resp_json = json.dumps({"response": str(response)})[:4000]

    with _db_lock:
        cur = conn.execute(
            """INSERT INTO delegation_execution_log
               (event_type, target_type, target_id,
                request_json, response_json, ok, error_message, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(event_type or ""),
                str(target_type or ""),
                int(target_id) if target_id is not None else None,
                req_json,
                resp_json,
                1 if ok else 0,
                error_message,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_delegation_executions(
    db_url: str,
    *,
    limit: int = 50,
    target_type: str | None = None,
    target_id: int | None = None,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    where: list[str] = []
    params: list[Any] = []
    if target_type:
        where.append("target_type = ?")
        params.append(str(target_type))
    if target_id is not None:
        where.append("target_id = ?")
        params.append(int(target_id))
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(lim)
    with _db_lock:
        rows = conn.execute(
            f"SELECT * FROM delegation_execution_log{clause} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def log_error_event(
    db_url: str,
    error_type: str,
    error_message: str,
    traceback_text: str | None = None,
    endpoint: str | None = None,
    request_data: str | None = None,
    agent_id: str = "orchestrator",
    resolved: bool = False,
    resolution: str | None = None,
) -> int:
    """Log an error event for self-healing analysis."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO error_log
               (error_type, error_message, traceback_text, endpoint,
                request_data, agent_id, resolved, resolution,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                error_type,
                error_message,
                traceback_text,
                endpoint,
                request_data,
                agent_id,
                resolved,
                resolution,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid  # type: ignore[return-value]


def get_recent_errors(
    db_url: str,
    limit: int = 20,
    unresolved_only: bool = False,
) -> list[dict[str, Any]]:
    """Get recent error events, optionally only unresolved ones."""
    conn = _get_conn(db_url)
    query = "SELECT * FROM error_log WHERE 1=1"
    params: list[Any] = []
    if unresolved_only:
        query += " AND resolved = 0"
    query += " ORDER BY created_at DESC LIMIT ?"
    params.append(limit)
    with _db_lock:
        rows = conn.execute(query, params).fetchall()
    return [dict(r) for r in rows]


def mark_error_resolved(
    db_url: str,
    error_id: int,
    resolution: str,
) -> None:
    """Mark an error as resolved with a description of the fix."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """UPDATE error_log
               SET resolved = 1, resolution = ?, updated_at = ?
               WHERE id = ?""",
            (resolution, now, error_id),
        )
        conn.commit()


def save_opt_out(db_url: str, phone: str, reason: str = "STOP") -> None:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """INSERT OR IGNORE INTO sms_opt_outs
               (phone_number, reason, created_at)
               VALUES (?, ?, ?)""",
            (phone, reason, now),
        )
        # Bounded retry so a lock that appears only at commit time is ridden
        # out.  The durable spool (app.services.sms_spool) is the real
        # guarantee; this just avoids a needless deferral.
        commit_retry(conn, attempts=4, base_delay=0.05)



def remove_opt_out_db(db_url: str, phone: str) -> None:
    conn = _get_conn(db_url)
    with _db_lock:
        conn.execute(
            "DELETE FROM sms_opt_outs WHERE phone_number = ?",
            (phone,),
        )
        commit_retry(conn, attempts=4, base_delay=0.05)



def save_opt_out_best_effort(
    db_url: str, phone: str, reason: str = "STOP"
) -> bool:
    """Persist a STOP opt-out without ever raising a transient lock error.

    The STOP branch of /webhook/twilio/sms called save_opt_out() directly, so a
    contended INSERT raised sqlite3.OperationalError out of the route and Twilio
    got a 500 it never retries (observed 2026-09-22T01:05:56Z).  The in-memory
    opt-out set applied by add_opt_out() is unaffected; the connection's
    ``busy_timeout`` is the bounded wait and a lock error is logged + swallowed.
    """
    try:
        save_opt_out(db_url, phone, reason)
        return True
    except sqlite3.OperationalError as exc:
        if not is_locked_error(exc):
            raise
        _log.warning(
            "opt-out not persisted (SQLite busy; in-memory STOP remains active): %s",
            exc,
        )
        return False


def remove_opt_out_db_best_effort(db_url: str, phone: str) -> bool:
    """Best-effort counterpart to :func:`remove_opt_out_db` (see above)."""
    try:
        remove_opt_out_db(db_url, phone)
        return True
    except sqlite3.OperationalError as exc:
        if not is_locked_error(exc):
            raise
        _log.warning(
            "opt-out removal not persisted (SQLite busy; in-memory state updated): %s",
            exc,
        )
        return False


def list_opt_outs(db_url: str) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM sms_opt_outs ORDER BY created_at DESC"
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Work sessions — long-running task tracking
# ---------------------------------------------------------------------------


def create_work_session(
    db_url: str,
    title: str,
    task_id: int | None = None,
    agent_id: str = "orchestrator",
    total_steps: int = 0,
    context: dict[str, Any] | None = None,
) -> int:
    """Create a new work session for a long-running task."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO work_sessions
               (task_id, agent_id, title, status, total_steps,
                context_json, started_at, updated_at)
               VALUES (?, ?, ?, 'active', ?, ?, ?, ?)""",
            (
                task_id,
                agent_id,
                title,
                total_steps,
                json.dumps(context or {}),
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


# The closed set of legal `work_sessions.status` values. Declared here so a
# writer cannot invent one: a status outside this set is invisible to every
# filter in the codebase, which is how 39 junk rows went unnoticed for months.
_WORK_SESSION_STATUSES = frozenset(
    {
        "active",
        "cancelled",
        "completed",
        "expired",
        "failed",
        "paused",
    }
)


def update_work_session(
    db_url: str,
    session_id: int,
    *,
    status: str | None = None,
    steps_completed: int | None = None,
    total_steps: int | None = None,
    progress_pct: int | None = None,
    output_append: str | None = None,
    context: dict[str, Any] | None = None,
) -> bool:
    """Update a work session's progress."""
    conn = _get_conn(db_url)
    now = _now_iso()
    updates: list[str] = []
    params: list[Any] = []
    if status is not None and status not in _WORK_SESSION_STATUSES:
        # Refuse junk rather than storing it. In June 2026 a test inserted 39 rows
        # with the columns shifted, leaving statuses like '5' and '4.81'. Nothing
        # rejected them, and because every sweep and every count filters on a known
        # status, those rows were invisible to the cleanup that should have caught
        # them: counted as neither success nor failure for three months.
        logging.getLogger(__name__).error(
            "update_work_session(%s): refusing unknown status %r; allowed: %s",
            session_id,
            status,
            ", ".join(sorted(_WORK_SESSION_STATUSES)),
        )
        status = None
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        # `paused` is terminal for the same reason `failed` is, and it was the only
        # one that left no ending behind. Measured on the authority 2026-10-15T14:32Z,
        # 30 d to 2026-10-15T14:15:06Z:
        #   SELECT status, SUM(completed_at IS NULL OR completed_at=''), COUNT(*)
        #     FROM work_sessions ... GROUP BY status;
        #   -> failed 0/1869, completed 0/1305, paused 153/153.
        # `paused` is already in `_WORK_SESSION_STATUSES` (app/database.py:9253) and in
        # AutopilotController._WORK_SESSION_TERMINAL_STATUSES (app/autopilot.py:78), so
        # the estate already records it as stopped for good -- a reader that takes
        # `completed_at` as "when it ended" was the only one left with nothing.
        if status in ("completed", "failed", "cancelled", "paused"):
            updates.append("completed_at = ?")
            params.append(now)
    if steps_completed is not None:
        updates.append("steps_completed = ?")
        params.append(steps_completed)
    if total_steps is not None:
        updates.append("total_steps = ?")
        params.append(total_steps)
    if progress_pct is not None:
        updates.append("progress_pct = ?")
        params.append(max(0, min(100, progress_pct)))
    if context is not None:
        updates.append("context_json = ?")
        params.append(json.dumps(context))
    if output_append:
        updates.append("output_log = output_log || ?")
        params.append(output_append + "\n")
    if not updates:
        return False
    updates.append("updated_at = ?")
    params.append(now)
    params.append(session_id)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE work_sessions SET {', '.join(updates)} " f"WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


def get_active_work_session(
    db_url: str,
    agent_id: str = "orchestrator",
) -> dict[str, Any] | None:
    """Get the currently active work session, if any."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM work_sessions "
            "WHERE agent_id = ? AND status = 'active' "
            "ORDER BY started_at DESC LIMIT 1",
            (agent_id,),
        ).fetchone()
    return dict(row) if row else None


def get_work_session(
    db_url: str,
    session_id: int,
) -> dict[str, Any] | None:
    """Get a work session by ID."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM work_sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_work_sessions(
    db_url: str,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List work sessions with optional filters."""
    conn = _get_conn(db_url)
    where: list[str] = []
    params: list[Any] = []
    if agent_id:
        where.append("agent_id = ?")
        params.append(agent_id)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with _db_lock:
        rows = conn.execute(
            f"SELECT * FROM work_sessions{clause} " f"ORDER BY started_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Job queue — persistent async work items
# ---------------------------------------------------------------------------


def _job_payload_task_id(payload_json: str | None) -> int | None:
    try:
        payload = json.loads(payload_json or "{}")
    except (TypeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict):
        return None
    task_id = payload.get("task_id")
    if isinstance(task_id, str) and task_id.isdigit():
        task_id = int(task_id)
    return task_id if isinstance(task_id, int) else None


def enqueue_job(
    db_url: str,
    job_type: str,
    title: str = "",
    payload: dict[str, Any] | None = None,
    priority: int = 5,
    agent_id: str = "orchestrator",
    max_retries: int = 3,
) -> int:
    """Add a job to the queue."""
    conn = _get_conn(db_url)
    agent_id = canonicalize_assignment_agent(agent_id) or "orchestrator"
    now = _now_iso()
    payload_data = payload or {}
    payload_json = json.dumps(payload_data)
    task_id = None
    if job_type == "task_execution":
        task_id = _job_payload_task_id(payload_json)
        # CRITICAL FIX (2026-08-08): Never enqueue work for a task that is
        # already completed/closed. Previously completed jobs were not
        # deduped, so every re-enqueue of a done task created a fresh job,
        # and work mode burned LLM sessions on already-finished work
        # (843 of 938 work sessions in 48h ran on done tasks).
        if task_id is not None:
            try:
                task_row = conn.execute(
                    "SELECT status FROM tasks WHERE id = ?", (task_id,)
                ).fetchone()
                task_status = str(
                    task_row["status"] if task_row else ""
                ).strip().lower()
                if task_status in TASK_COMPLETED_STATUSES:
                    return 0
            except Exception:  # noqa: BLE001
                pass  # best-effort; enqueue proceeds if lookup fails
    with _db_lock:
        if task_id is not None:
            rows = conn.execute(
                "SELECT id, status, priority, payload_json FROM job_queue "
                "WHERE job_type = 'task_execution' "
                "AND status IN ('pending', 'running') "
                "ORDER BY priority DESC, created_at ASC"
            ).fetchall()
            for row in rows:
                if _job_payload_task_id(row["payload_json"]) != task_id:
                    continue
                existing_id = int(row["id"])
                if str(row["status"] or "") == "pending":
                    conn.execute(
                        "UPDATE job_queue SET agent_id = ?, title = ?, "
                        "payload_json = ?, priority = CASE "
                        "WHEN priority < ? THEN ? ELSE priority END "
                        "WHERE id = ?",
                        (
                            agent_id,
                            title,
                            payload_json,
                            priority,
                            priority,
                            existing_id,
                        ),
                    )
                    conn.commit()
                return existing_id

        cur = conn.execute(
            """INSERT INTO job_queue
               (agent_id, job_type, title, payload_json, status,
                priority, max_retries, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?)""",
            (
                agent_id,
                job_type,
                title,
                payload_json,
                priority,
                max_retries,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def complete_duplicate_task_jobs(
    db_url: str,
    *,
    limit: int = 10000,
) -> int:
    """Complete duplicate pending task_execution jobs for the same task id."""
    conn = _get_conn(db_url)
    scan_limit = max(1, min(50000, int(limit or 10000)))
    seen_task_ids: set[int] = set()
    duplicate_ids: list[int] = []

    with _db_lock:
        rows = conn.execute(
            "SELECT id, payload_json FROM job_queue "
            "WHERE status = 'pending' AND job_type = 'task_execution' "
            "ORDER BY priority DESC, created_at ASC LIMIT ?",
            (scan_limit,),
        ).fetchall()
        for row in rows:
            task_id = _job_payload_task_id(row["payload_json"])
            if task_id is None:
                continue
            if task_id in seen_task_ids:
                duplicate_ids.append(int(row["id"]))
            else:
                seen_task_ids.add(task_id)

        if not duplicate_ids:
            return 0

        now = _now_iso()
        placeholders = ", ".join("?" for _ in duplicate_ids)
        result = json.dumps(
            {
                "status": "completed",
                "reason": "duplicate_task_execution_job",
            }
        )
        conn.execute(
            "UPDATE job_queue SET status = 'completed', result_json = ?, "
            f"completed_at = ? WHERE id IN ({placeholders})",
            [result, now, *duplicate_ids],
        )
        conn.commit()
        return len(duplicate_ids)


def claim_next_job(
    db_url: str,
    agent_id: str = "orchestrator",
    job_type: str | None = None,
) -> dict[str, Any] | None:
    """Atomically claim the next pending job for this agent."""
    conn = _get_conn(db_url)
    agent_id = canonicalize_assignment_agent(agent_id) or "orchestrator"
    now = _now_iso()
    with _db_lock:
        if job_type:
            row = conn.execute(
                "SELECT * FROM job_queue "
                "WHERE agent_id = ? AND status = 'pending' AND job_type = ? "
                "ORDER BY priority DESC, created_at ASC LIMIT 1",
                (agent_id, job_type),
            ).fetchone()
        else:
            row = conn.execute(
                "SELECT * FROM job_queue "
                "WHERE agent_id = ? AND status = 'pending' "
                "ORDER BY priority DESC, created_at ASC LIMIT 1",
                (agent_id,),
            ).fetchone()
        if not row:
            return None
        job = dict(row)
        conn.execute(
            "UPDATE job_queue SET status = 'running', " "picked_up_at = ? WHERE id = ?",
            (now, job["id"]),
        )
        conn.commit()
        job["status"] = "running"
        job["picked_up_at"] = now
        return job


def claim_next_job_for_agent_pool(
    db_url: str,
    agent_ids: list[str] | tuple[str, ...],
    job_type: str | None = None,
) -> dict[str, Any] | None:
    """Atomically claim the highest-priority pending job for any known agent."""
    normalized_agent_ids: list[str] = []
    seen: set[str] = set()
    for raw_agent_id in agent_ids:
        agent_id = canonicalize_assignment_agent(raw_agent_id)
        if not agent_id or agent_id in seen:
            continue
        normalized_agent_ids.append(agent_id)
        seen.add(agent_id)
    if not normalized_agent_ids:
        return None

    conn = _get_conn(db_url)
    now = _now_iso()
    placeholders = ", ".join("?" for _ in normalized_agent_ids)
    params: list[Any] = list(normalized_agent_ids)
    type_clause = ""
    if job_type:
        type_clause = "AND job_type = ? "
        params.append(job_type)

    with _db_lock:
        row = conn.execute(
            "SELECT * FROM job_queue "
            f"WHERE agent_id IN ({placeholders}) AND status = 'pending' "
            f"{type_clause}"
            "ORDER BY priority DESC, created_at ASC LIMIT 1",
            params,
        ).fetchone()
        if not row:
            return None
        job = dict(row)
        conn.execute(
            "UPDATE job_queue SET status = 'running', picked_up_at = ? WHERE id = ?",
            (now, job["id"]),
        )
        conn.commit()
        job["status"] = "running"
        job["picked_up_at"] = now
        return job


def complete_stale_task_jobs(
    db_url: str,
    *,
    limit: int = 500,
) -> int:
    """Complete pending task jobs whose underlying tasks are already closed."""
    conn = _get_conn(db_url)
    scan_limit = max(1, min(10000, int(limit or 500)))
    completed_ids: list[int] = []
    completed_statuses = {status.lower() for status in TASK_COMPLETED_STATUSES}

    with _db_lock:
        rows = conn.execute(
            "SELECT id, payload_json FROM job_queue "
            "WHERE status = 'pending' AND job_type = 'task_execution' "
            "ORDER BY priority DESC, created_at ASC LIMIT ?",
            (scan_limit,),
        ).fetchall()
        for row in rows:
            try:
                payload = json.loads(row["payload_json"] or "{}")
            except (TypeError, json.JSONDecodeError):
                continue
            task_id = payload.get("task_id") if isinstance(payload, dict) else None
            if isinstance(task_id, str) and task_id.isdigit():
                task_id = int(task_id)
            if not isinstance(task_id, int):
                continue
            task_row = conn.execute(
                "SELECT status FROM tasks WHERE id = ?",
                (task_id,),
            ).fetchone()
            status = str(task_row["status"] if task_row else "").strip().lower()
            if status in completed_statuses:
                completed_ids.append(int(row["id"]))

        if not completed_ids:
            return 0

        now = _now_iso()
        placeholders = ", ".join("?" for _ in completed_ids)
        result = json.dumps(
            {
                "status": "completed",
                "reason": "underlying_task_already_closed",
            }
        )
        conn.execute(
            "UPDATE job_queue SET status = 'completed', result_json = ?, "
            f"completed_at = ? WHERE id IN ({placeholders})",
            [result, now, *completed_ids],
        )
        conn.commit()
        return len(completed_ids)


def complete_job(
    db_url: str,
    job_id: int,
    result: dict[str, Any] | None = None,
) -> bool:
    """Mark a job as completed."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            "UPDATE job_queue SET status = 'completed', "
            "result_json = ?, completed_at = ? WHERE id = ?",
            (json.dumps(result or {}), now, job_id),
        )
        conn.commit()
        return cur.rowcount > 0


def fail_job(
    db_url: str,
    job_id: int,
    error_message: str = "",
) -> bool:
    """Mark a job as failed or re-queue if retries remain."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        row = conn.execute(
            "SELECT retry_count, max_retries FROM job_queue " "WHERE id = ?",
            (job_id,),
        ).fetchone()
        if not row:
            return False
        if row["retry_count"] < row["max_retries"]:
            conn.execute(
                "UPDATE job_queue SET status = 'pending', "
                "retry_count = retry_count + 1, "
                "error_message = ? WHERE id = ?",
                (error_message, job_id),
            )
        else:
            conn.execute(
                "UPDATE job_queue SET status = 'failed', "
                "error_message = ?, completed_at = ? WHERE id = ?",
                (error_message, now, job_id),
            )
        conn.commit()
        return True


def count_recent_failed_work_sessions(
    db_url: str,
    task_id: int | None,
    *,
    within_hours: int = 24,
) -> int:
    """How many work sessions have already failed or been paused on this task recently.

    Nothing else notices that the same work has been attempted and failed: a job
    exists, so a session is created, so the same LLM budget is spent again. Measured
    2026-09-15: task #25106 was attempted five times in ninety minutes and every attempt
    died at the step budget.

    Bounded to recent failures on purpose. A task that failed three times last week and
    has new work today is not the same situation as one failing three times this hour,
    and blocking the former would be a silent loss of work.
    """
    if not task_id:
        return 0
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, int(within_hours)))
    ).isoformat()
    conn = _get_conn(db_url)
    row = conn.execute(
        # `paused` is deliberately NOT counted here. Measured on the authority
        # 2026-10-15 after a change that DID count it: of 13 tasks that paused 3+ times
        # in 30 d, **5 went on to COMPLETE** (38 %), against 9 of 482 for `failed`
        # (1.9 %). Task 28625 paused six consecutive times (78754, 78756, 78759, 78763,
        # 78768, 78771), failed once, then completed (78779) -- counting `paused` would
        # have refused it at the third pause (78759), four attempts before it finished.
        # A budget pause means the session ran out of room, not that the work is
        # hopeless, and round 4's own notes call it "not a loop failure". Retry CONTEXT
        # still inherits a paused attempt (attempt_context.PRIOR_ATTEMPT_STATUSES);
        # that is a different question and it is proven by observed sessions.
        "SELECT count(*) FROM work_sessions "
        "WHERE task_id = ? AND status = 'failed' AND started_at >= ?",
        (int(task_id), cutoff),
    ).fetchone()
    return int(row[0] if row else 0)


def retire_abandoned_running_jobs(
    db_url: str,
    *,
    older_than_hours: int = 24,
    note: str = "abandoned: stuck in running with no reachable cleanup",
) -> int:
    """Fail jobs that have been 'running' longer than any plausible work session.

    Two conditions are deliberately waived, because both hid real rows:
      * the agent filter -- requeue_stale_running_jobs is scoped to one agent, so a
        job claimed by any other agent is never examined again. Nine such rows sat
        running for 41 to 90 days.
      * `picked_up_at IS NOT NULL` -- the oldest rows predate the column, so
        requiring it made them permanently invisible.

    Completed-task jobs are the caller's business (complete_stale_task_jobs runs
    first); what is left here is work nobody will ever pick up, so it is failed with
    a reason rather than requeued into fresh LLM spend.
    """
    from datetime import datetime, timedelta, timezone

    conn = _get_conn(db_url)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
    with _db_lock:
        cur = conn.execute(
            "UPDATE job_queue "
            "SET status = 'failed', completed_at = ?, error_message = ? "
            "WHERE status = 'running' "
            "AND coalesce(picked_up_at, created_at) < ?",
            (now.isoformat(), note, cutoff),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def requeue_stale_running_jobs(
    db_url: str,
    *,
    agent_id: str = "orchestrator",
    stale_after_sec: int = 3600,
    note: str = "stale running job requeued",
) -> int:
    """Requeue jobs stuck in 'running' status for too long.

    This protects work_mode from permanently losing jobs if the process
    crashes or a work session fails to initialize after claiming.
    """
    from datetime import datetime, timedelta, timezone

    conn = _get_conn(db_url)
    now = datetime.now(timezone.utc)
    stale_seconds = max(60, int(stale_after_sec))
    cutoff = (now - timedelta(seconds=stale_seconds)).isoformat()
    with _db_lock:
        cur = conn.execute(
            "UPDATE job_queue "
            "SET status = 'pending', "
            "retry_count = retry_count + 1, "
            "error_message = ?, "
            "picked_up_at = NULL "
            "WHERE agent_id = ? "
            "AND status = 'running' "
            "AND picked_up_at IS NOT NULL "
            "AND picked_up_at < ?",
            (note, agent_id, cutoff),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def list_jobs(
    db_url: str,
    agent_id: str | None = None,
    status: str | None = None,
    limit: int = 20,
) -> list[dict[str, Any]]:
    """List jobs with optional filters."""
    conn = _get_conn(db_url)
    where: list[str] = []
    params: list[Any] = []
    if agent_id:
        where.append("agent_id = ?")
        params.append(agent_id)
    if status:
        where.append("status = ?")
        params.append(status)
    clause = (" WHERE " + " AND ".join(where)) if where else ""
    params.append(limit)
    with _db_lock:
        rows = conn.execute(
            f"SELECT * FROM job_queue{clause} "
            f"ORDER BY priority DESC, created_at ASC LIMIT ?",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Progress checkpoints — save intermediate state
# ---------------------------------------------------------------------------


def save_checkpoint(
    db_url: str,
    session_id: int,
    step_number: int,
    label: str = "",
    context: dict[str, Any] | None = None,
    output_text: str = "",
) -> int:
    """Save a progress checkpoint for a work session."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO progress_checkpoints
               (session_id, step_number, label, context_json,
                output_text, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                session_id,
                step_number,
                label,
                json.dumps(context or {}),
                output_text,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_latest_checkpoint(
    db_url: str,
    session_id: int,
) -> dict[str, Any] | None:
    """Get the most recent checkpoint for a work session."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM progress_checkpoints "
            "WHERE session_id = ? "
            "ORDER BY step_number DESC LIMIT 1",
            (session_id,),
        ).fetchone()
    return dict(row) if row else None


def list_checkpoints(
    db_url: str,
    session_id: int,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent progress checkpoints for a work session (chronological)."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM progress_checkpoints "
            "WHERE session_id = ? "
            "ORDER BY step_number DESC LIMIT ?",
            (session_id, lim),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Subtask helpers — hierarchical task queries
# ---------------------------------------------------------------------------


def get_subtasks(
    db_url: str,
    parent_task_id: int,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """Get child tasks of a parent task."""
    conn = _get_conn(db_url)
    where = "parent_task_id = ?"
    params: list[Any] = [parent_task_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    with _db_lock:
        rows = conn.execute(
            f"SELECT * FROM tasks WHERE {where} ORDER BY id ASC",
            params,
        ).fetchall()
    return [dict(r) for r in rows]


def update_task_progress(
    db_url: str,
    task_id: int,
    progress_pct: int,
) -> bool:
    """Update just the progress percentage of a task."""
    conn = _get_conn(db_url)
    now = _now_iso()
    pct = max(0, min(100, progress_pct))
    with _db_lock:
        cur = conn.execute(
            "UPDATE tasks SET progress_pct = ?, updated_at = ? " "WHERE id = ?",
            (pct, now, task_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Missions / OKR tracking
# ---------------------------------------------------------------------------


def create_mission(
    db_url: str,
    title: str,
    description: str = "",
    key_results: str = "",
    timeframe: str = "month",
    proposed_by: str = "orchestrator",
) -> int:
    """Create a new mission (OKR) in proposed state."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO missions
               (title, description, key_results, timeframe,
                status, progress_pct, proposed_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 'proposed', 0, ?, ?, ?)""",
            (title, description, key_results, timeframe, proposed_by, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_missions(
    db_url: str,
    status: str = "active",
) -> list[dict[str, Any]]:
    """List missions, optionally filtered by status."""
    conn = _get_conn(db_url)
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM missions ORDER BY created_at DESC"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM missions WHERE status = ? " "ORDER BY created_at DESC",
            (status,),
        ).fetchall()
    return [dict(r) for r in rows]


def update_mission(
    db_url: str,
    mission_id: int,
    status: str | None = None,
    progress_pct: int | None = None,
    notes: str | None = None,
) -> bool:
    """Update a mission's status and/or progress."""
    conn = _get_conn(db_url)
    now = _now_iso()
    updates = ["updated_at = ?"]
    params: list[Any] = [now]

    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status == "active":
            updates.append("approved_at = ?")
            params.append(now)
    if progress_pct is not None:
        updates.append("progress_pct = ?")
        params.append(max(0, min(100, progress_pct)))
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)

    params.append(mission_id)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE missions SET {', '.join(updates)} " f"WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


def get_active_missions(db_url: str) -> list[dict[str, Any]]:
    """Get all active (approved) missions for prompt injection."""
    conn = _get_conn(db_url)
    rows = conn.execute(
        "SELECT * FROM missions "
        "WHERE status IN ('active', 'proposed') "
        "ORDER BY status ASC, created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Owner Profile (Shadow Profile / Owner Manual)
# ---------------------------------------------------------------------------


def upsert_owner_profile(
    db_url: str,
    key: str,
    value: str,
    confidence: float = 0.5,
    source: str = "inferred",
) -> None:
    """Upsert an owner profile fact."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        conn.execute(
            """INSERT INTO owner_profile
               (key, value, confidence, source, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(key) DO UPDATE SET
                 value = excluded.value,
                 confidence = excluded.confidence,
                 source = excluded.source,
                 updated_at = excluded.updated_at""",
            (key, value, confidence, source, now),
        )
        conn.commit()
    try:
        from app.services.owner_model import sync_legacy_owner_profile

        sync_legacy_owner_profile(db_url, keys=[key])
    except Exception:
        _log.warning(
            "Failed to mirror owner_profile fact %s into owner model",
            key,
            exc_info=True,
        )


def get_owner_profile(db_url: str) -> dict[str, Any]:
    """Get all owner profile facts as a dict."""
    conn = _get_conn(db_url)
    rows = conn.execute(
        "SELECT key, value, confidence, source " "FROM owner_profile ORDER BY key"
    ).fetchall()
    return {
        r["key"]: {
            "value": r["value"],
            "confidence": r["confidence"],
            "source": r["source"],
        }
        for r in rows
    }


def create_owner_assumption(
    db_url: str,
    *,
    key: str,
    value: str,
    confidence: float = 0.5,
    evidence: str = "",
    proposed_by: str = "orchestrator",
) -> int:
    """Create an owner assumption that requires confirmation.

    This is used to avoid the system treating inferred preferences/state as facts.
    """
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO owner_assumptions
               (key, value, confidence, evidence, status, proposed_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 'proposed', ?, ?, ?)""",
            (key, value, float(confidence), evidence, proposed_by, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_owner_assumptions(
    db_url: str,
    *,
    status: str = "proposed",
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List owner assumptions, optionally filtered by status."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM owner_assumptions ORDER BY updated_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM owner_assumptions WHERE status = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    return [dict(r) for r in rows]


def confirm_owner_assumption(
    db_url: str,
    assumption_id: int,
    *,
    promote_to_profile: bool = True,
    profile_source: str = "owner_confirmed",
) -> bool:
    """Confirm an assumption; optionally promote it to owner_profile."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        row = conn.execute(
            "SELECT id, key, value, confidence FROM owner_assumptions WHERE id = ?",
            (assumption_id,),
        ).fetchone()
        if not row:
            return False

        cur = conn.execute(
            "UPDATE owner_assumptions SET status = 'confirmed', "
            "confirmed_at = ?, updated_at = ? WHERE id = ?",
            (now, now, assumption_id),
        )
        if cur.rowcount <= 0:
            conn.commit()
            return False

        if promote_to_profile:
            try:
                upsert_owner_profile(
                    db_url,
                    key=str(row["key"]),
                    value=str(row["value"]),
                    confidence=max(float(row["confidence"] or 0.5), 0.9),
                    source=profile_source,
                )
            except Exception:
                pass

        conn.commit()
        return True


def reject_owner_assumption(
    db_url: str,
    assumption_id: int,
) -> bool:
    """Reject an assumption."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            "UPDATE owner_assumptions SET status = 'rejected', "
            "rejected_at = ?, updated_at = ? WHERE id = ?",
            (now, now, assumption_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Spend requests (wallet scaffolding)
# ---------------------------------------------------------------------------


def create_spend_request(
    db_url: str,
    *,
    title: str,
    description: str = "",
    vendor: str = "",
    amount_usd: float | None = None,
    currency: str = "USD",
    requested_by: str = "orchestrator",
) -> int:
    """Create a spend request (approval-first; no payment execution)."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO spend_requests
               (title, description, vendor, amount_usd, currency,
                status, requested_by, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'proposed', ?, ?, ?)""",
            (
                title,
                description,
                vendor,
                amount_usd,
                (currency or "USD"),
                requested_by,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_spend_requests(
    db_url: str,
    *,
    status: str = "proposed",
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM spend_requests ORDER BY updated_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM spend_requests WHERE status = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    return [dict(r) for r in rows]


def get_spend_request(
    db_url: str,
    request_id: int,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM spend_requests WHERE id = ?",
            (int(request_id),),
        ).fetchone()
    return dict(row) if row else None


def update_spend_request(
    db_url: str,
    request_id: int,
    *,
    status: str,
) -> bool:
    """Update spend request status to approved/rejected/etc."""
    conn = _get_conn(db_url)
    now = _now_iso()
    updates = ["status = ?", "updated_at = ?"]
    params: list[Any] = [status, now]
    if status == "approved":
        updates.append("approved_at = ?")
        params.append(now)
    if status == "rejected":
        updates.append("rejected_at = ?")
        params.append(now)
    params.append(request_id)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE spend_requests SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Human delegation job drafts (approval-first; no Upwork API yet)
# ---------------------------------------------------------------------------


def create_human_job(
    db_url: str,
    *,
    title: str,
    description: str = "",
    platform: str = "upwork",
    budget_usd: float | None = None,
    job_post_text: str = "",
    requested_by: str = "orchestrator",
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO human_jobs
               (title, description, platform, budget_usd,
                status, job_post_text, requested_by,
                created_at, updated_at)
               VALUES (?, ?, ?, ?, 'proposed', ?, ?, ?, ?)""",
            (
                title,
                description,
                platform or "upwork",
                budget_usd,
                job_post_text,
                requested_by,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_human_jobs(
    db_url: str,
    *,
    status: str = "proposed",
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM human_jobs ORDER BY updated_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM human_jobs WHERE status = ? "
            "ORDER BY updated_at DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    return [dict(r) for r in rows]


def get_human_job(
    db_url: str,
    job_id: int,
) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM human_jobs WHERE id = ?",
            (int(job_id),),
        ).fetchone()
    return dict(row) if row else None


def update_human_job(
    db_url: str,
    job_id: int,
    *,
    status: str | None = None,
    job_post_text: str | None = None,
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    updates = ["updated_at = ?"]
    params: list[Any] = [now]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status == "approved":
            updates.append("approved_at = ?")
            params.append(now)
        if status == "rejected":
            updates.append("rejected_at = ?")
            params.append(now)
    if job_post_text is not None:
        updates.append("job_post_text = ?")
        params.append(job_post_text)

    params.append(job_id)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE human_jobs SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Owner feedback events (implicit learning signals)
# ---------------------------------------------------------------------------


def log_owner_feedback_event(
    db_url: str,
    *,
    event_type: str,
    target_type: str,
    target_id: int | None = None,
    payload: dict[str, Any] | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO owner_feedback_events
               (event_type, target_type, target_id, payload_json, created_at)
               VALUES (?, ?, ?, ?, ?)""",
            (
                event_type,
                target_type,
                target_id,
                json.dumps(payload or {}),
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def upsert_owner_weekly_feedback(
    db_url: str,
    *,
    week_key: str,
    score: int,
    comment: str = "",
    source: str = "sms",
) -> dict[str, Any]:
    """Insert/update the owner's weekly 1-5 rating.

    Enforces one feedback row per week_key.
    """
    wk = str(week_key or "").strip()
    if not wk:
        raise ValueError("week_key is required")

    try:
        s = int(score)
    except Exception as exc:
        raise ValueError("score must be an int") from exc
    if s < 1 or s > 5:
        raise ValueError("score must be between 1 and 5")

    conn = _get_conn(db_url)
    now = _now_iso()
    src = str(source or "sms").strip() or "sms"
    cmt = str(comment or "").strip()

    with _db_lock:
        conn.execute(
            """INSERT INTO owner_weekly_feedback (week_key, score, comment, source, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(week_key) DO UPDATE SET
                 score = excluded.score,
                 comment = excluded.comment,
                 source = excluded.source,
                 created_at = excluded.created_at
            """,
            (wk, s, cmt, src, now),
        )
        conn.commit()

        row = conn.execute(
            "SELECT * FROM owner_weekly_feedback WHERE week_key = ?",
            (wk,),
        ).fetchone()

    return (
        dict(row)
        if row
        else {
            "week_key": wk,
            "score": s,
            "comment": cmt,
            "source": src,
            "created_at": now,
        }
    )


def list_owner_weekly_feedback(
    db_url: str,
    *,
    limit: int = 12,
) -> list[dict[str, Any]]:
    """List recent weekly owner ratings, newest-first."""
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 12)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM owner_weekly_feedback ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


#: Reason prefixes whose rows are deduplicated by OBLIGATION, not by wording.
#: Scoped deliberately: collapsing two differently-worded messages is only safe for a
#: family we know is the same recurring thing re-phrased. A reminder is; an alert is not.
_OWNER_OBLIGATION_REASONS = ("reminder:",)

#: High-entropy identifiers that name the SUBJECT of a message. Presence of one of these
#: in two bodies means the two are about the same thing whatever their wording.
_OBLIGATION_SUBJECT_RES = (
    re.compile(r"\bVIN\s*[:#]?\s*([A-HJ-NPR-Z0-9]{11,17})\b", re.I),
    re.compile(r"\bpolicy\s*[:#]?\s*([A-Z0-9]{6,20})\b", re.I),
    re.compile(r"\bticket\s*[:#]?\s*(\d{3,10})\b", re.I),
    re.compile(r"\border\s*[:#]?\s*(\d{4,12})\b", re.I),
)


def owner_obligation_key(reason: Any, body: Any) -> str | None:
    """A stable key for WHAT a message is about, ignoring how it is worded.

    Returns None for a reason family that is not deduplicated by obligation, which is
    every family except the ones named in ``_OWNER_OBLIGATION_REASONS``.

    WHY THIS EXISTS, measured on the authority 2026-09-30. The owner's car has had no
    fire, theft or collision cover since 19 May 2026. Between 25 and 29 September the
    system created FIVE reminders about it -- ids 504, 521, 522, 523, 524 -- each with
    slightly different wording of the same obligation ("Elantra physical damage coverage
    still suspended ...", "ACTION NEEDED: Schedule the Carco inspection ..."). Every one
    was delivered into ``owner_message_queue`` as its own row, because the existing dedup
    key is the ``(reason, body)`` pair and the reason is ``reminder:<new id>`` every time.

    The consequence was not only five rows: ``_owner_message_deserves_escalation`` ages a
    row from ``last_seen_at``, and a row created nine minutes ago is nine minutes old, so
    the 24-hour escalation that exists for exactly this case could never fire. Row 2034
    shows the outcome -- 276 recorded send attempts, refused every time with "urgency
    'normal' is below the send threshold 'urgent'". The obligation was queued, refused,
    re-queued under a new id, refused again, for five days, and never reached him.

    The subject identifier (a VIN, a policy, a ticket, an order) is what makes two
    differently-worded messages the same obligation. Failing that, a normalised body hash,
    which still collapses the exact repeat case.
    """
    family = str(reason or "").strip().lower()
    if not any(family == r or family.startswith(r) for r in _OWNER_OBLIGATION_REASONS):
        return None
    text = str(body or "")
    lowered = text.casefold()
    # The owner can say "don't tell me this again" about a topic. That is not an obligation.
    for pattern in _OBLIGATION_SUBJECT_RES:
        found = pattern.search(text)
        if found:
            kind = pattern.pattern.split(r"\b")[1].split(r"\s")[0].lower()
            return "%s:%s" % (kind, found.group(1).upper())
    # No structured subject: only collapse an exact repeat, on normalised words, and only
    # when the message is short enough that two of them really are the same sentence.
    words = re.findall(r"[a-z0-9]+", lowered)
    if len(words) < 6:
        return None
    return "text:" + hashlib.sha256(" ".join(words[:60]).encode()).hexdigest()[:24]


_OWNER_MSG_COLUMNS_ENSURED: set[str] = set()


def _ensure_owner_message_columns(db_url: str, conn) -> None:
    """Add ``repeat_count`` / ``last_seen_at`` to ``owner_message_queue`` if absent.

    SQLite has no ``ADD COLUMN IF NOT EXISTS``, and ``CREATE TABLE IF NOT EXISTS``
    does not add columns to a table that already exists — so the dedup below would
    raise ``no such column`` on every pre-existing database, including the
    authority's 3 GB one. This makes the migration lazy, idempotent and cached per
    database URL.
    """
    if db_url in _OWNER_MSG_COLUMNS_ENSURED:
        return
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(owner_message_queue)")}
    except Exception:  # noqa: BLE001 - a missing table is not this function's problem
        return
    if not cols:
        return
    with _db_lock:  # reentrant: enqueue_owner_message already holds it
        if "repeat_count" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN repeat_count INTEGER DEFAULT 1"
            )
        if "last_seen_at" not in cols:
            conn.execute("ALTER TABLE owner_message_queue ADD COLUMN last_seen_at TEXT")
        # Delivery attempts and their last error. Added 2026-09-15: a failed owner SMS left
        # no trace anywhere -- no log, no counter, no status change -- so 42 undelivered
        # urgent/critical alerts read exactly like health. A message that cannot be sent
        # must say so on its own row.
        if "send_attempts" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN send_attempts INTEGER DEFAULT 0"
            )
        if "last_send_error" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN last_send_error TEXT"
            )
        # Why a row left the queue. Added 2026-09-15 with the shelf-life phase: until
        # then nothing aged this table at all, so a row's status was the only trace
        # that it had been dropped, and "expired" could not distinguish a five-week-old
        # briefing from a real alert.
        # The obligation a message is about, so the same recurring thing reworded is
        # recognised. Added 2026-09-30; see owner_obligation_key for the measurement.
        if "obligation_key" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN obligation_key TEXT"
            )
        if "status_note" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN status_note TEXT"
            )
        # When this row may next be attempted. Added 2026-10-10 (housekeeping item
        # 581): measured 2026-10-08, one library reminder was re-attempted 489 times
        # in ten hours (488 suppressed + 1 delivered, one attempt every ~70 s) because
        # record_owner_message_send_failure counted the attempt but left the row
        # immediately retryable, so the once-a-minute flush re-drove it forever.
        if "next_attempt_at" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN next_attempt_at TEXT"
            )
        # Deliver once, on the owner's next inbound. Added 2026-10-20 (housekeeping
        # item 314). Before this, a text the flood guard DEFERRED was written back
        # with its reason and left immediately retryable, so the once-a-minute flush
        # re-offered the identical body until the opener breaker dismissed it -- the
        # owner's own measure of the defect was "5 times in the last hour". His
        # decision (owner_decision_queue #497, 2026-10-15) was "deliver once, when you
        # reply". The states are deliberately few:
        #   0  not waiting for anything (every ordinary row)
        #   1  parked: waiting for his next inbound, invisible to due_only
        #   2  released by that inbound: exactly one delivery attempt remains
        if "deliver_on_inbound" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN deliver_on_inbound "
                "INTEGER DEFAULT 0"
            )
        # The stable subject of the message, carried from the producer. Added 2026-10-25
        # (housekeeping item 1279). Measured: eight paraphrased reminders for NJ
        # sales-tax packet #29749 were enqueued in one batch, the composer stripped
        # "#29749" from every body, and the relay topic ledger therefore keyed each one
        # on its first five words. This column is where the sender puts the subject it
        # still knows, so the 20h reminder cooldown can see one matter instead of eight
        # wordings. NULL is every pre-2026-10-25 row and means "derive from the body".
        if "subject_key" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN subject_key TEXT"
            )
        conn.commit()
    _OWNER_MSG_COLUMNS_ENSURED.add(db_url)


def enqueue_owner_message(
    db_url: str,
    *,
    body: str,
    reason: str = "",
    urgency: str = "normal",
    status: str | None = None,
    subject_key: str = "",
) -> int:
    """Queue or hold an owner SMS candidate.

    ``subject_key`` is the stable identity of the thing the message is about, carried
    from the producer that still holds the original text (``case:29749`` for a finance
    packet). It rides on the row so the flush and the relay topic ledger do not have to
    re-derive an identity from a body the reminder composer has already stripped of ids.
    Empty is the old behaviour.

    Messages below the persisted owner SMS urgency threshold are retained with
    status ``held`` so they remain available for review without being flushed
    to the owner's phone later.

    **Deduplicated against an identical undelivered message** (added 2026-09-14).
    Measured on the authority: of 326 rows sitting ``held``, 158 were exact
    duplicates of a single body — ``sync_breaker:ebay_sync`` 74 rows with **one**
    distinct body, ``sync_breaker:amazon_sync`` 74 with one, and
    ``financial_alert:reversal`` 10 with one — while ``ask_owner`` held 95 distinct
    bodies that are all real. That half-a-queue of repeats is what made an
    all-or-nothing kill switch look necessary (P51); a repeat is one finding
    observed again, not a new finding.

    So: if the same ``reason`` and ``body`` are already undelivered, this does not
    insert a second row. It bumps ``repeat_count`` and ``last_seen_at`` on the
    existing one and returns its id, which keeps the recurrence visible without
    making the queue unreadable. Deduping by the pair is deliberately narrow — it
    cannot collapse two findings that differ in wording, and every distinct
    ``ask_owner`` question survives.
    """
    conn = _get_conn(db_url)
    now = _now_iso()
    # This body goes out as an SMS to the owner and is stored here; when an agent
    # asks about a customer it quotes the customer's text, card digits included.
    # Redact before the dedup SELECT below so the (reason, body) key compares
    # redacted-to-redacted and a repeat still collapses onto one row.
    body = redact_body_for_storage(body)
    subject_value = str(subject_key or "").strip()
    status_value = (
        str(status).strip().lower()
        if status is not None
        else (
            "queued" if _owner_sms_allowed_for_db(db_url, urgency=urgency) else "held"
        )
    )
    if status_value not in {"queued", "held"}:
        raise ValueError(f"Invalid owner message enqueue status: {status!r}")
    # Dedup against an identical undelivered message (added 2026-09-14).
    # Measured: of 326 rows sitting held, 158 were exact duplicates of a single
    # body -- sync_breaker:ebay_sync 74 rows with ONE distinct body,
    # sync_breaker:amazon_sync 74 with one, financial_alert:reversal 10 with one
    # -- while ask_owner held 95 distinct bodies, all real. That half-a-queue of
    # repeats is what made an all-or-nothing kill switch look necessary (P51).
    # A repeat is one finding observed again, not a new finding: it belongs in
    # repeat_count, not in another row. Keying on the (reason, body) pair is
    # deliberately narrow, so two findings that differ in wording both survive.
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        # DEDUPED ON THE BODY, NOT ON (reason, body). Measured 2026-09-30: the
        # reminder dispatcher stamps a fresh `reason` on every fire -- `reminder:521`,
        # `reminder:524`, `reminder:488` -- so ONE repeating reminder became a NEW row
        # each time and the (reason, body) key never matched. Four identical Elantra
        # inspection reminders were created inside five hours that day, and because
        # `last_seen_at` is written at insert too, each new row was 0 hours old for
        # escalation purposes. The escalation that exists for exactly this case
        # (`_owner_message_deserves_escalation`, 24 h) could therefore NEVER fire for a
        # repeating reminder: the more often the system tried, the younger the row got.
        # That is the structural reason obligations were refused 200-600 times and never
        # reached his phone. The body is what he reads; the reason is our bookkeeping and
        # stays on the surviving row.
        # AND ON THE OBLIGATION, for the families where the same recurring thing is
        # repeatedly re-worded. The body match above cannot collapse those, and a
        # membership test over recent rows is O(n) with a Python-side normaliser;
        # `owner_obligation_key` gives a stable key we can store and index-free compare.
        obligation = owner_obligation_key(reason, body)
        has_obligation = False
        try:
            has_obligation = any(
                row[1] == "obligation_key"
                for row in conn.execute("PRAGMA table_info(owner_message_queue)")
            )
        except Exception:  # noqa: BLE001 - a pre-migration table just uses the body key
            has_obligation = False
        if obligation and has_obligation:
            existing = conn.execute(
                """SELECT id FROM owner_message_queue
                   WHERE obligation_key = ? AND status IN ('held', 'queued')
                   ORDER BY created_at DESC LIMIT 1""",
                (obligation,),
            ).fetchone()
            if existing is not None:
                conn.execute(
                    """UPDATE owner_message_queue
                       SET repeat_count = COALESCE(repeat_count, 1) + 1,
                           subject_key = COALESCE(NULLIF(subject_key, ''), ?)
                       WHERE id = ?""",
                    (subject_value, existing["id"]),
                )
                conn.commit()
                return int(existing["id"])
        existing = conn.execute(
            """SELECT id FROM owner_message_queue
               WHERE body = ? AND status IN ('held', 'queued')
               ORDER BY created_at DESC LIMIT 1""",
            (body,),
        ).fetchone()
        if existing is not None:
            # last_seen_at is NOT moved by an exact repeat. It is the row's AGE, and
            # `_owner_message_deserves_escalation` turns a row into a text after 24 h of
            # no action. A reminder that fires every few hours and resets its own age clock
            # can therefore never age, which is measured: row 2034 (the Elantra's lapsed
            # insurance) accumulated 276 refused send attempts and never once reached the
            # escalation that exists for it. `created_at` stays, `repeat_count` counts the
            # repeats, and `last_seen_at` keeps meaning "when this row was last genuinely
            # new". A repeat is evidence the reminder is still pending, not evidence it
            # just appeared.
            conn.execute(
                """UPDATE owner_message_queue
                   SET repeat_count = COALESCE(repeat_count, 1) + 1,
                       subject_key = COALESCE(NULLIF(subject_key, ''), ?)
                   WHERE id = ?""",
                (subject_value, existing["id"]),
            )
            conn.commit()
            return int(existing["id"])
        if obligation and has_obligation:
            cur = conn.execute(
                """INSERT INTO owner_message_queue
                   (body, reason, urgency, status, created_at, repeat_count, last_seen_at,
                    obligation_key, subject_key)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)""",
                (body, reason, urgency, status_value, now, now, obligation, subject_value),
            )
        else:
            cur = conn.execute(
                """INSERT INTO owner_message_queue
                   (body, reason, urgency, status, created_at, repeat_count, last_seen_at,
                    subject_key)
                   VALUES (?, ?, ?, ?, ?, 1, ?, ?)""",
                (body, reason, urgency, status_value, now, now, subject_value),
            )
        conn.commit()
        return cur.lastrowid or 0


_OWNER_SMS_URGENCY_ORDER = {
    "low": -1,
    "normal": 0,
    "medium": 1,
    "high": 1,
    "urgent": 2,
    "stuck": 2,
    "critical": 3,
}


def _owner_sms_urgency_rank(raw: Any) -> int:
    value = str(raw or "normal").strip().lower()
    return _OWNER_SMS_URGENCY_ORDER.get(value, _OWNER_SMS_URGENCY_ORDER["normal"])


def _owner_sms_allowed_for_db(db_url: str, *, urgency: Any = "normal") -> bool:
    try:
        overrides = list_settings_overrides(db_url)
        threshold = overrides.get("owner_sms_min_urgency", "normal")
    except Exception:
        threshold = "normal"
    return _owner_sms_urgency_rank(urgency) >= _owner_sms_urgency_rank(threshold)


def clear_owner_message_backoff(
    db_url: str, message_id: int, *, reset_attempts: bool = False
) -> bool:
    """Clear a refused row's retry clock because the refusal was not about it.

    ``record_owner_message_send_failure`` backs a row off exponentially, and that
    is right for a transient sender failure.  It is wrong for a refusal that names
    only our configuration ("urgency 'normal' is below the send threshold"): the
    message has not changed, so waiting six hours cannot change the verdict.  The
    owner-channel triage clears the clock when the row's class earns a send, so
    the ordinary send pass -- with every real gate in front of it -- can judge it.
    """
    conn = _get_conn(db_url)
    with _db_lock:
        sets = "next_attempt_at = NULL"
        if reset_attempts:
            # THE BUDGET MUST NOT BE SPENT ON REFUSALS ABOUT OUR CONFIG.
            # Measured 2026-10-21: three health reminders carried 10-11
            # threshold refusals, then one real rate-floor refusal carried
            # them past the 12-attempt budget and they were dismissed. The
            # attempts were never attempts at the message.
            sets += ", send_attempts = 0"
        cur = conn.execute(
            "UPDATE owner_message_queue SET " + sets + " "
            "WHERE id = ? AND status IN ('held', 'queued')",
            (int(message_id),),
        )
        conn.commit()
        return bool(cur.rowcount)


def list_owner_message_queue(
    db_url: str,
    *,
    status: str = "queued",
    limit: int = 25,
    due_only: bool = False,
    now: datetime | None = None,
) -> list[dict[str, Any]]:
    """Rows in ``status``, newest first.

    ``due_only`` excludes a row whose ``next_attempt_at`` is still in the future -- i.e.
    one a previous refusal has already asked us not to re-attempt yet. The owner-message
    flush passes it so a refused row stops taking its slot on every 60-second tick (item
    581: 488 suppressed attempts in ten hours for one reminder). Every other caller keeps
    the old selection: they read the queue to describe it, not to send from it.
    """
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 25)))
    if status == "all":
        rows = conn.execute(
            "SELECT * FROM owner_message_queue ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    elif due_only:
        moment = now or datetime.now(timezone.utc)
        if moment.tzinfo is None:
            moment = moment.replace(tzinfo=timezone.utc)
        _ensure_owner_message_columns(db_url, conn)
        rows = conn.execute(
            "SELECT * FROM owner_message_queue WHERE status = ? "
            "AND (next_attempt_at IS NULL OR next_attempt_at <= ?) "
            "ORDER BY created_at DESC LIMIT ?",
            (status, moment.isoformat(), lim),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM owner_message_queue WHERE status = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    return [dict(r) for r in rows]




def clear_owner_sync_alerts(
    db_url: str,
    subsystem: str,
    *,
    evidence: str = "",
) -> int:
    """Resolve the sync alerts a subsystem raised, now that it has succeeded.

    Added 2026-09-15. amazon_sync and ebay_sync each raised a
    `sync_needs_login:*` row when their saved browser sessions expired, and
    nothing ever cleared one: both sessions were re-authenticated on the morning
    of 2026-09-15, a real sync ingested transactions at 04:30, and the two
    `urgent` rows were still `held` that afternoon -- counted by the kernel's
    attention-debt check and shown on the owner's badge as work waiting for him.
    An alert whose condition is gone is not an alert; it is a false reading that
    spends the owner's attention.

    Called from the one place every sync outcome passes through, so the alert and
    its clear cannot drift apart. Returns the number of rows resolved.
    """
    name = str(subsystem or "").strip()
    if not name:
        return 0
    conn = _get_conn(db_url)
    note = f"resolved: {name} succeeded"
    if str(evidence or "").strip():
        note = f"{note} ({str(evidence).strip()[:160]})"
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        try:
            cur = conn.execute(
                "UPDATE owner_message_queue SET status = 'resolved', status_note = ? "
                "WHERE status IN ('held', 'queued') AND (reason = ? OR reason = ?)",
                (note, f"sync_needs_login:{name}", f"sync_breaker:{name}"),
            )
            conn.commit()
        except Exception as exc:  # noqa: BLE001 - never break the caller's health record
            _log.warning("clear_owner_sync_alerts(%s) failed: %s", name, exc)
            return 0
    return int(cur.rowcount or 0)


def mark_owner_message_sent(
    db_url: str,
    message_id: int,
) -> bool:
    return mark_owner_message_status(db_url, message_id, status="sent")


#: Owner-message retry backoff. A refused message is re-attempted on this curve,
#: never on the flush tick itself.
#:
#: Measured 2026-10-08 (housekeeping item 581): the library reminder was attempted
#: 489 times in ten hours -- 488 suppressed, one delivered, one attempt every ~70 s.
#: `record_owner_message_send_failure` counted the attempt and left the row
#: `queued`, so the once-a-minute flush re-picked it forever and nothing made the
#: delay grow. The delay now doubles from one flush tick (60 s) up to a six-hour
#: ceiling: over those ten hours the count is ~10, not 489. The ageing pass in
#: owner_sms_flood_guard remains the terminal answer for a row never accepted.
OWNER_MESSAGE_RETRY_BASE_SECONDS = 60
OWNER_MESSAGE_RETRY_MAX_SECONDS = 6 * 60 * 60


def _owner_message_next_attempt_at(
    attempts: int,
    *,
    now: datetime,
    retry_after: str | None = None,
) -> str:
    """Earliest time a refused owner message may be attempted again.

    ``retry_after`` is the gate's own verdict, when it gave one -- ``app.owner_text.gate``
    returns it for the rate floor and for an open turn -- and honouring it beats any
    curve, because the gate is what knows why it refused. Otherwise the delay doubles
    from one flush tick up to :data:`OWNER_MESSAGE_RETRY_MAX_SECONDS`.
    """
    if retry_after:
        try:
            candidate = datetime.fromisoformat(str(retry_after).replace("Z", "+00:00"))
            if candidate.tzinfo is None:
                candidate = candidate.replace(tzinfo=timezone.utc)
            if candidate > now:
                return candidate.isoformat()
        except Exception:  # noqa: BLE001 - an unparseable hint is not a reason to retry now
            pass
    delay = min(
        OWNER_MESSAGE_RETRY_BASE_SECONDS * (2 ** max(0, int(attempts) - 1)),
        OWNER_MESSAGE_RETRY_MAX_SECONDS,
    )
    return (now + timedelta(seconds=delay)).isoformat()


def record_owner_message_send_failure(
    db_url: str,
    message_id: int,
    reason: str,
    *,
    retry_after: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Record that an owner message could not be sent, and why, and when to retry.

    Added 2026-09-15. The flush had no failure branch, so a send that failed was
    indistinguishable from one that was never attempted: it stayed `held`, was retried at the
    same position in the queue forever, and nothing surfaced the reason. Measured at the time:
    42 urgent/critical messages held and unsent, an urgent briefing re-attempted thousands of
    times over 5.7 hours with no recorded cause, and 2 messages sent in 7 days.

    Extended 2026-10-10 (item 581). That branch recorded the failure but not the *rate*: the
    row stayed immediately retryable, so the once-a-minute flush re-attempted it on a fixed
    interval -- 488 suppressed rows in ten hours for one reminder. The attempt now also writes
    ``next_attempt_at``, and ``list_owner_message_queue(due_only=True)`` is what the flush
    reads, so a refused message waits on a doubling delay instead of being re-driven every
    tick. ``send_attempts`` keeps counting every refusal, so the row still says how hard it
    was tried.
    """
    conn = _get_conn(db_url)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        # last_seen_at is deliberately NOT touched here. It means "when was this
        # condition last observed" (enqueue stamps it only on a dedup hit), and the
        # shelf-life phase ages messages on it. Writing it on a failed send made a
        # five-week-old briefing look freshly seen -- which would have defeated the
        # ageing policy the same day it was added.
        row = conn.execute(
            "SELECT COALESCE(send_attempts, 0) FROM owner_message_queue WHERE id = ?",
            (int(message_id),),
        ).fetchone()
        if row is None:
            return False
        attempts = int(row[0] or 0) + 1
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET send_attempts = ?, last_send_error = ?, next_attempt_at = ? "
            "WHERE id = ?",
            (
                attempts,
                str(reason or "")[:300],
                _owner_message_next_attempt_at(
                    attempts, now=moment, retry_after=retry_after
                ),
                int(message_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0




def defer_owner_message_retry(
    db_url: str,
    message_id: int,
    reason: str,
    *,
    retry_after: str | None = None,
    now: datetime | None = None,
) -> bool:
    """Schedule a clock-only refusal without spending the attempt budget.

    THE ATTEMPT BUDGET IS FOR FAULTS, NOT FOR APPOINTMENTS (L4, 2026-10-25).
    ``record_owner_message_send_failure`` is the right writer for a send that
    failed: something was tried, it did not work, and the number of times it was
    tried is evidence. The text gate's pacing refusals are the opposite. The gate
    refuses *before* any delivery attempt and returns ``retry_after`` -- the
    exact moment its own rate floor, turn grace, similar hold or topic cooldown
    lifts. Retrying then is not churn; it is the appointment the gate made.

    Measured 2026-10-25: fifteen reminders carried 8-9 attempts after 3.5 hours
    because a ``similar_hold`` retry is only ~25 minutes away, and the twelve-
    attempt cap -- sized for the 60 s doubling curve, where twelve attempts span
    twenty-plus hours -- would have dismissed them *before* the hold's own cliff
    released them. Every one of those counts was the owner's own pacing rule.

    This writer therefore updates ``last_send_error``, ``status_note`` and
    ``next_attempt_at`` and deliberately leaves ``send_attempts`` untouched, for
    the same reason ``note_owner_message_deferral`` does. A refusal with no
    parseable clock falls back to the doubling curve in the caller's own writer;
    this function is only called when the gate supplied a moment.

    Returns False for a missing or already-terminal row, like the failure writer.
    """
    conn = _get_conn(db_url)
    moment = now or datetime.now(timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    note = str(reason or "")[:300]
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        row = conn.execute(
            "SELECT COALESCE(send_attempts, 0) FROM owner_message_queue "
            "WHERE id = ? AND status IN ('held', 'queued')",
            (int(message_id),),
        ).fetchone()
        if row is None:
            return False
        attempts = int(row[0] or 0)
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET last_send_error = ?, status_note = ?, next_attempt_at = ? "
            "WHERE id = ? AND status IN ('held', 'queued')",
            (
                note,
                note,
                _owner_message_next_attempt_at(
                    attempts, now=moment, retry_after=retry_after
                ),
                int(message_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0




def note_owner_message_deferral(
    db_url: str,
    message_id: int,
    reason: str,
    *,
    status: str | None = None,
) -> bool:
    """Record on the row that a flood ceiling deferred or dropped it, and why.

    Added 2026-09-22 with the owner-SMS ceilings. ``send_attempts`` is deliberately NOT
    touched: a ceiling stops the message *before* any delivery attempt, and inflating the
    attempt count would make a deferred message look like a failing one. What has to change
    is the row's own account of itself, because for two months the kill switch held ten rows
    that read exactly like rows that had never been reached -- ``send_attempts = 0`` and
    ``last_send_error IS NULL`` on every one, with nothing on the row saying a switch was
    holding them. ``reason`` is written to both ``last_send_error`` (so "why is this still
    here" has one answer) and ``status_note`` (the field the shelf-life phase already reads).

    ``status`` is optional: pass ``"dismissed"`` for a body-level duplicate, which is a
    repeat rather than a finding and must leave the queue; leave it ``None`` to keep the
    message queued or held for a retry once the window has moved on.
    """
    conn = _get_conn(db_url)
    note = str(reason or "")[:300]
    safe_status: str | None = None
    if status is not None:
        safe_status = str(status).strip().lower()
        if safe_status not in {"queued", "held", "sent", "dismissed", "cancelled"}:
            raise ValueError(f"Invalid owner message status: {status!r}")
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        if safe_status is None:
            cur = conn.execute(
                "UPDATE owner_message_queue SET status_note = ?, last_send_error = ? "
                "WHERE id = ?",
                (note, note, int(message_id)),
            )
        else:
            cur = conn.execute(
                "UPDATE owner_message_queue SET status = ?, status_note = ?, "
                "last_send_error = ? WHERE id = ?",
                (safe_status, note, note, int(message_id)),
            )
        conn.commit()
        return cur.rowcount > 0


#: A parked owner message is put beyond every retry window with this sentinel, so
#: ``list_owner_message_queue(due_only=True)`` cannot select it even if the clock is
#: wrong by decades. It is not a date the row should reach: the release clears it.
OWNER_MESSAGE_WAITING_FOR_INBOUND = "9999-12-31T23:59:59+00:00"


def defer_owner_message_until_inbound(
    db_url: str,
    message_id: int,
    reason: str,
    *,
    now: datetime | None = None,
) -> bool:
    """Park a flood-guard refusal until the owner next texts in.

    The owner's decision, 2026-10-15 (owner_decision_queue #497, housekeeping item
    314): *"deliver once, when you reply."* The defect it answers is in the old
    behaviour here: a deferred message was written back with its reason and left
    immediately retryable, so the once-a-minute flush re-offered the identical body
    until the opener breaker dismissed it. He measured it himself as "5 times in the
    last hour".

    A parked row is ``held``, carries the refusal reason in ``status_note`` and
    ``last_send_error``, and has ``deliver_on_inbound = 1``. Its ``next_attempt_at``
    is the sentinel above, so no due-only selection can pick it up. Only an inbound
    from the owner releases it, through
    :func:`release_owner_messages_on_inbound`.

    ``send_attempts`` is deliberately not touched: the ceiling stopped the message
    *before* any delivery attempt, and counting it would make a waiting message look
    like a failing one (`note_owner_message_deferral` makes the same distinction).
    """
    conn = _get_conn(db_url)
    note = str(reason or "")[:300]
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET status = 'held', status_note = ?, last_send_error = ?, "
            "next_attempt_at = ?, deliver_on_inbound = 1 "
            "WHERE id = ? AND status IN ('held', 'queued')",
            (
                note,
                note,
                OWNER_MESSAGE_WAITING_FOR_INBOUND,
                int(message_id),
            ),
        )
        conn.commit()
        return cur.rowcount > 0


def release_owner_messages_on_inbound(
    db_url: str,
    *,
    limit: int = 1,
    now: datetime | None = None,
) -> list[int]:
    """Release the message(s) parked for the owner's next inbound.

    Called from :func:`app.owner_text.handle_owner_reply`, i.e. only when the owner
    actually texts in. One row by default, oldest first: "deliver once, when you
    reply" is one text on his phone, not a burst of everything that accumulated.

    A released row keeps its refusal reason on ``status_note``/``last_send_error``,
    becomes due (``next_attempt_at`` cleared) and is marked
    ``deliver_on_inbound = 2`` -- the flush's signal that this is the one delivery
    he was promised, so it is not deferred or retried a second time.

    Returns the ids released, so the caller can record what happened.
    """
    wanted = max(0, int(limit))
    if wanted == 0:
        return []
    conn = _get_conn(db_url)
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        rows = conn.execute(
            "SELECT id FROM owner_message_queue "
            "WHERE deliver_on_inbound = 1 AND status IN ('held', 'queued') "
            "ORDER BY id ASC LIMIT ?",
            (wanted,),
        ).fetchall()
        ids = [int(row[0]) for row in rows]
        for message_id in ids:
            conn.execute(
                "UPDATE owner_message_queue "
                "SET next_attempt_at = NULL, deliver_on_inbound = 2, status = 'held' "
                "WHERE id = ? AND deliver_on_inbound = 1",
                (message_id,),
            )
        conn.commit()
    return ids


def mark_owner_message_status(
    db_url: str,
    message_id: int,
    *,
    status: str,
) -> bool:
    safe_status = str(status or "").strip().lower()
    if safe_status not in {"queued", "held", "sent", "dismissed", "cancelled"}:
        raise ValueError(f"Invalid owner message status: {status!r}")
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        if safe_status == "sent":
            cur = conn.execute(
                "UPDATE owner_message_queue SET status = 'sent', sent_at = ? WHERE id = ?",
                (now, message_id),
            )
        else:
            cur = conn.execute(
                "UPDATE owner_message_queue SET status = ?, sent_at = NULL WHERE id = ?",
                (safe_status, message_id),
            )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Personal Operations Capture + Reminders
# ---------------------------------------------------------------------------


def _decode_json_object(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return dict(raw)
    try:
        loaded = json.loads(str(raw or "{}"))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _capture_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    item["owner_needed"] = bool(item.get("owner_needed"))
    item["routed_to"] = _decode_json_object(item.pop("routed_to_json", "{}"))
    item["metadata"] = _decode_json_object(item.pop("metadata_json", "{}"))
    return item


def create_capture_inbox_item(
    db_url: str,
    *,
    raw_text: str,
    normalized_text: str = "",
    kind: str = "note",
    status: str = "captured",
    confidence: float = 0.0,
    source_channel: str = "manual",
    source_ref: str = "",
    sensitivity: str = "normal",
    owner_needed: bool = False,
    routed_to: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    expires_at: str | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO captures_inbox
               (raw_text, normalized_text, kind, status, confidence,
                source_channel, source_ref, sensitivity, owner_needed,
                routed_to_json, metadata_json, expires_at, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                raw_text,
                normalized_text,
                kind,
                status,
                confidence,
                source_channel,
                source_ref,
                sensitivity,
                1 if owner_needed else 0,
                json.dumps(routed_to or {}),
                json.dumps(metadata or {}),
                expires_at,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def update_capture_inbox_item(
    db_url: str,
    capture_id: int,
    *,
    status: str | None = None,
    owner_needed: bool | None = None,
    routed_to: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
) -> bool:
    updates: list[str] = ["updated_at = ?"]
    params: list[Any] = [_now_iso()]
    if status is not None:
        updates.append("status = ?")
        params.append(status)
    if owner_needed is not None:
        updates.append("owner_needed = ?")
        params.append(1 if owner_needed else 0)
    if routed_to is not None:
        updates.append("routed_to_json = ?")
        params.append(json.dumps(routed_to))
    if metadata is not None:
        updates.append("metadata_json = ?")
        params.append(json.dumps(metadata))
    params.append(capture_id)
    conn = _get_conn(db_url)
    with _db_lock:
        cur = conn.execute(
            f"UPDATE captures_inbox SET {', '.join(updates)} WHERE id = ?",
            params,
        )
        conn.commit()
        return cur.rowcount > 0


def list_capture_inbox_items(
    db_url: str,
    *,
    status: str = "all",
    kind: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 50)))
    conditions: list[str] = []
    params: list[Any] = []
    if status != "all":
        conditions.append("status = ?")
        params.append(status)
    if kind:
        conditions.append("kind = ?")
        params.append(kind)
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(lim)
    with _db_lock:
        rows = conn.execute(
            f"SELECT * FROM captures_inbox {where} ORDER BY created_at DESC LIMIT ?",
            params,
        ).fetchall()
    return [_capture_row_to_dict(row) for row in rows]


def _reminder_row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    reminder = dict(row)
    reminder["requires_ack"] = bool(reminder.get("requires_ack"))
    reminder["quiet_hours_override"] = bool(reminder.get("quiet_hours_override"))
    reminder["metadata"] = _decode_json_object(reminder.pop("metadata_json", "{}"))
    return reminder


def create_reminder(
    db_url: str,
    *,
    message: str,
    scheduled_time: str,
    source: str = "manual",
    source_ref: str = "",
    priority: str = "normal",
    requires_ack: bool = True,
    recurrence: str | None = None,
    delivery_channel: str = "dashboard",
    quiet_hours_override: bool = False,
    metadata: dict[str, Any] | None = None,
    legacy_id: str | None = None,
) -> int:
    conn = _get_conn(db_url)
    now = _now_iso()
    safe_metadata = dict(metadata or {})
    with _db_lock:
        if legacy_id:
            existing = conn.execute(
                "SELECT id FROM reminders WHERE legacy_id = ?",
                (legacy_id,),
            ).fetchone()
            if existing:
                return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO reminders
               (message, scheduled_time, source, source_ref, status, priority,
                requires_ack, recurrence, delivery_channel, quiet_hours_override,
                metadata_json, legacy_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                message,
                scheduled_time,
                source,
                source_ref,
                priority,
                1 if requires_ack else 0,
                recurrence,
                delivery_channel,
                1 if quiet_hours_override else 0,
                json.dumps(safe_metadata),
                legacy_id,
                now,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def get_reminder(db_url: str, reminder_id: int) -> dict[str, Any] | None:
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT * FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
    return _reminder_row_to_dict(row) if row else None


def list_reminders(
    db_url: str,
    *,
    status: str = "active",
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    lim = max(1, min(200, int(limit or 50)))
    if status == "active":
        sql = (
            "SELECT * FROM reminders WHERE status IN "
            "('pending','sent','snoozed') ORDER BY scheduled_time ASC LIMIT ?"
        )
        params: tuple[Any, ...] = (lim,)
    elif status == "attention":
        sql = (
            "SELECT * FROM reminders WHERE status IN ('sent','snoozed') "
            "ORDER BY COALESCE(snooze_until, scheduled_time) ASC LIMIT ?"
        )
        params = (lim,)
    elif status == "all":
        sql = "SELECT * FROM reminders ORDER BY scheduled_time DESC LIMIT ?"
        params = (lim,)
    else:
        sql = "SELECT * FROM reminders WHERE status = ? ORDER BY scheduled_time ASC LIMIT ?"
        params = (status, lim)
    with _db_lock:
        rows = conn.execute(sql, params).fetchall()
    return [_reminder_row_to_dict(row) for row in rows]


def list_due_reminders(
    db_url: str,
    *,
    now_iso: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    conn = _get_conn(db_url)
    now = now_iso or _now_iso()
    lim = max(1, min(200, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            """SELECT * FROM reminders
               WHERE (status = 'pending' AND scheduled_time <= ?)
                  OR (status = 'snoozed' AND snooze_until IS NOT NULL AND snooze_until <= ?)
               ORDER BY scheduled_time ASC
               LIMIT ?""",
            (now, now, lim),
        ).fetchall()
    return [_reminder_row_to_dict(row) for row in rows]


def mark_reminder_delivered(
    db_url: str,
    reminder_id: int,
    *,
    delivered_at: str | None = None,
) -> bool:
    conn = _get_conn(db_url)
    now = delivered_at or _now_iso()
    with _db_lock:
        row = conn.execute(
            "SELECT requires_ack FROM reminders WHERE id = ?",
            (reminder_id,),
        ).fetchone()
        if not row:
            return False
        next_status = "sent" if bool(row["requires_ack"]) else "expired"
        cur = conn.execute(
            """UPDATE reminders
               SET status = ?, last_delivered_at = ?, delivery_attempts = delivery_attempts + 1,
                   updated_at = ?, snooze_until = NULL
               WHERE id = ?""",
            (next_status, now, now, reminder_id),
        )
        conn.commit()
        return cur.rowcount > 0


def update_reminder_status(
    db_url: str,
    reminder_id: int,
    *,
    status: str,
    snooze_until: str | None = None,
    metadata_patch: dict[str, Any] | None = None,
) -> bool:
    safe_status = str(status or "").strip().lower()
    if safe_status not in {
        "pending",
        "sent",
        "acked",
        "snoozed",
        "expired",
        "cancelled",
    }:
        raise ValueError(f"Invalid reminder status: {status!r}")
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        metadata_json = None
        if metadata_patch:
            row = conn.execute(
                "SELECT metadata_json FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
            current = _decode_json_object(row["metadata_json"] if row else "{}")
            current.update(metadata_patch)
            metadata_json = json.dumps(current)

        if metadata_json is not None:
            cur = conn.execute(
                """UPDATE reminders
                   SET status = ?, snooze_until = ?, metadata_json = ?, updated_at = ?
                   WHERE id = ?""",
                (safe_status, snooze_until, metadata_json, now, reminder_id),
            )
        else:
            cur = conn.execute(
                """UPDATE reminders
                   SET status = ?, snooze_until = ?, updated_at = ?
                   WHERE id = ?""",
                (safe_status, snooze_until, now, reminder_id),
            )
        conn.commit()
        return cur.rowcount > 0


def reschedule_reminder(
    db_url: str,
    reminder_id: int,
    *,
    scheduled_time: str,
    metadata_patch: dict[str, Any] | None = None,
) -> bool:
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        metadata_json = None
        if metadata_patch:
            row = conn.execute(
                "SELECT metadata_json FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
            current = _decode_json_object(row["metadata_json"] if row else "{}")
            current.update(metadata_patch)
            metadata_json = json.dumps(current)
        if metadata_json is not None:
            cur = conn.execute(
                """UPDATE reminders
                   SET status = 'pending', scheduled_time = ?, snooze_until = NULL,
                       metadata_json = ?, updated_at = ?
                   WHERE id = ?""",
                (scheduled_time, metadata_json, now, reminder_id),
            )
        else:
            cur = conn.execute(
                """UPDATE reminders
                   SET status = 'pending', scheduled_time = ?, snooze_until = NULL,
                       updated_at = ?
                   WHERE id = ?""",
                (scheduled_time, now, reminder_id),
            )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Owner State (user_state)
# ---------------------------------------------------------------------------


def get_owner_state(
    db_url: str,
    *,
    key: str = "current",
) -> dict[str, Any]:
    """Fetch the latest owner state JSON by key."""
    conn = _get_conn(db_url)
    with _db_lock:
        row = conn.execute(
            "SELECT key, value_json, updated_at FROM owner_state WHERE key = ?",
            (key,),
        ).fetchone()
    if not row:
        return {
            "key": key,
            "value": {},
            "updated_at": None,
        }

    raw = row["value_json"]
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (json.JSONDecodeError, TypeError, ValueError):
        value = raw
    return {
        "key": row["key"],
        "value": value,
        "updated_at": row["updated_at"],
    }


def set_owner_state(
    db_url: str,
    *,
    key: str = "current",
    value: Any,
) -> str:
    """Upsert owner state JSON. Returns updated_at ISO string."""
    conn = _get_conn(db_url)
    now = _now_iso()
    try:
        value_json = json.dumps(value)
    except TypeError as exc:
        msg = f"Owner state value for {key!r} is not JSON-serializable"
        raise ValueError(msg) from exc

    with _db_lock:
        conn.execute(
            """INSERT INTO owner_state (key, value_json, updated_at)
               VALUES (?, ?, ?)
               ON CONFLICT(key) DO UPDATE
               SET value_json = excluded.value_json,
                   updated_at = excluded.updated_at""",
            (key, value_json, now),
        )
        conn.commit()
    if key == "current":
        try:
            from app.services.owner_model import sync_owner_state_context

            sync_owner_state_context(db_url)
        except Exception:
            _log.warning(
                "Failed to mirror owner_state into owner model",
                exc_info=True,
            )
    return now


# ---------------------------------------------------------------------------
# Event Triage Log
# ---------------------------------------------------------------------------


def log_triage_event(
    db_url: str,
    source: str,
    event_type: str,
    summary: str,
    classification: str = "ignore",
    action_taken: str = "",
    raw_data: str = "{}",
) -> int:
    """Log an event triage decision."""
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            """INSERT INTO event_triage_log
               (source, event_type, summary, classification,
                action_taken, raw_data, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (source, event_type, summary, classification, action_taken, raw_data, now),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_triage_events(
    db_url: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """List recent triage log entries (chronological)."""
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM event_triage_log ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in reversed(rows)]


# ---------------------------------------------------------------------------
# Unified Approval Queue
# ---------------------------------------------------------------------------


def list_pending_approvals(
    db_url: str,
    *,
    limit: int = 50,
) -> list[dict[str, Any]]:
    """Return all pending approval items across all types.

    Merges missions, spend_requests, human_jobs, and
    owner_assumptions that are in 'proposed' status into
    a single sorted list.
    """
    results: list[dict[str, Any]] = []

    missions = list_missions(db_url, status="proposed")
    for m in missions:
        results.append(
            {
                "type": "mission",
                "id": m.get("id"),
                "title": str(m.get("title") or ""),
                "description": str(m.get("description") or ""),
                "created_at": str(m.get("created_at") or ""),
                "agent_id": str(m.get("proposed_by") or ""),
                "amount": None,
            }
        )

    spend = list_spend_requests(db_url, status="proposed", limit=limit)
    for s in spend:
        results.append(
            {
                "type": "spend_request",
                "id": s.get("id"),
                "title": str(s.get("description") or ""),
                "description": str(s.get("justification") or ""),
                "created_at": str(s.get("created_at") or ""),
                "agent_id": str(s.get("agent_id") or ""),
                "amount": s.get("amount_usd"),
            }
        )

    jobs = list_human_jobs(db_url, status="proposed", limit=limit)
    for j in jobs:
        results.append(
            {
                "type": "human_job",
                "id": j.get("id"),
                "title": str(j.get("title") or ""),
                "description": str(j.get("description") or ""),
                "created_at": str(j.get("created_at") or ""),
                "agent_id": str(j.get("agent_id") or ""),
                "amount": j.get("budget_usd"),
            }
        )

    assumptions = list_owner_assumptions(db_url, status="proposed", limit=limit)
    for a in assumptions:
        results.append(
            {
                "type": "assumption",
                "id": a.get("id"),
                "title": str(a.get("key") or ""),
                "description": str(a.get("value") or ""),
                "created_at": str(a.get("created_at") or ""),
                "agent_id": str(a.get("agent_id") or ""),
                "amount": None,
            }
        )

    # Sort by created_at descending (newest first)
    results.sort(
        key=lambda x: str(x.get("created_at") or ""),
        reverse=True,
    )

    return results[:limit]


def approve_item(
    db_url: str,
    *,
    item_type: str,
    item_id: int,
) -> bool:
    """Approve a single pending item by type and ID."""
    if item_type == "mission":
        return update_mission(db_url, item_id, status="active")
    elif item_type == "spend_request":
        return _update_status(db_url, "spend_requests", item_id, "approved")
    elif item_type == "human_job":
        return _update_status(db_url, "human_jobs", item_id, "approved")
    elif item_type == "assumption":
        return _update_status(db_url, "owner_assumptions", item_id, "confirmed")
    return False


def reject_item(
    db_url: str,
    *,
    item_type: str,
    item_id: int,
) -> bool:
    """Reject a single pending item by type and ID."""
    if item_type == "mission":
        return update_mission(db_url, item_id, status="rejected")
    elif item_type in ("spend_request", "human_job"):
        table = "spend_requests" if item_type == "spend_request" else "human_jobs"
        return _update_status(db_url, table, item_id, "rejected")
    elif item_type == "assumption":
        return _update_status(db_url, "owner_assumptions", item_id, "rejected")
    return False


def _update_status(
    db_url: str,
    table: str,
    item_id: int,
    status: str,
) -> bool:
    """Generic status update helper."""
    # Whitelist tables to prevent injection
    allowed = {
        "spend_requests",
        "human_jobs",
        "owner_assumptions",
    }
    if table not in allowed:
        return False
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            f"UPDATE {table} SET status = ?, " f"updated_at = ? WHERE id = ?",
            (status, now, item_id),
        )
        conn.commit()
        return cur.rowcount > 0


# ---------------------------------------------------------------------------
# Operation Journal
# ---------------------------------------------------------------------------


def _ensure_operation_journal_table(db_url: str) -> None:
    """Create operation_journal table if it doesn't exist."""
    conn = _get_conn(db_url)
    with _db_lock:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS operation_journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                operation_type TEXT NOT NULL,
                description TEXT NOT NULL DEFAULT '',
                agent_id TEXT NOT NULL DEFAULT '',
                status TEXT NOT NULL DEFAULT 'running',
                started_at TEXT NOT NULL,
                completed_at TEXT,
                result TEXT,
                error TEXT,
                metadata_json TEXT
            )
        """)
        conn.commit()


def start_operation(
    db_url: str,
    *,
    operation_type: str,
    description: str = "",
    agent_id: str = "",
    metadata: dict[str, Any] | None = None,
) -> int:
    """Record the start of an operation. Returns op ID."""
    import json

    _ensure_operation_journal_table(db_url)
    conn = _get_conn(db_url)
    now = _now_iso()
    meta_json = json.dumps(metadata) if metadata else None
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO operation_journal "
            "(operation_type, description, agent_id, "
            "status, started_at, metadata_json) "
            "VALUES (?, ?, ?, 'running', ?, ?)",
            (
                operation_type,
                description,
                agent_id,
                now,
                meta_json,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def complete_operation(
    db_url: str,
    op_id: int,
    *,
    result: str = "",
) -> bool:
    """Mark an operation as completed."""
    _ensure_operation_journal_table(db_url)
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            "UPDATE operation_journal "
            "SET status = 'completed', "
            "completed_at = ?, result = ? "
            "WHERE id = ?",
            (now, result, op_id),
        )
        conn.commit()
        return cur.rowcount > 0


def fail_operation(
    db_url: str,
    op_id: int,
    *,
    error: str = "",
) -> bool:
    """Mark an operation as failed."""
    _ensure_operation_journal_table(db_url)
    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        cur = conn.execute(
            "UPDATE operation_journal "
            "SET status = 'failed', "
            "completed_at = ?, error = ? "
            "WHERE id = ?",
            (now, error, op_id),
        )
        conn.commit()
        return cur.rowcount > 0


def get_stale_operations(
    db_url: str,
    *,
    older_than_minutes: int = 60,
) -> list[dict[str, Any]]:
    """Find operations that are still 'running' but old."""
    _ensure_operation_journal_table(db_url)
    conn = _get_conn(db_url)
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(minutes=older_than_minutes)
    ).isoformat()
    with _db_lock:
        rows = conn.execute(
            "SELECT * FROM operation_journal "
            "WHERE status = 'running' "
            "AND started_at < ? "
            "ORDER BY started_at ASC",
            (cutoff,),
        ).fetchall()
    return [dict(r) for r in rows]


def list_operations(
    db_url: str,
    *,
    limit: int = 50,
    status: str | None = None,
) -> list[dict[str, Any]]:
    """List recent operations."""
    _ensure_operation_journal_table(db_url)
    conn = _get_conn(db_url)
    lim = max(1, min(500, int(limit or 50)))
    if status:
        rows = conn.execute(
            "SELECT * FROM operation_journal "
            "WHERE status = ? "
            "ORDER BY started_at DESC LIMIT ?",
            (status, lim),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM operation_journal " "ORDER BY started_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Policy Audit Log
# ---------------------------------------------------------------------------


def _ensure_policy_audit_table(db_url: str) -> None:
    """Create policy_audit_log table if it doesn't exist."""
    conn = _get_conn(db_url)
    with _db_lock:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS policy_audit_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                action_name TEXT NOT NULL,
                agent_id TEXT NOT NULL DEFAULT '',
                decision TEXT NOT NULL,
                reason TEXT NOT NULL DEFAULT '',
                tier TEXT,
                params_json TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.commit()


def log_policy_decision(
    db_url: str,
    *,
    action_name: str,
    agent_id: str = "",
    decision: str = "allowed",
    reason: str = "",
    tier: str = "",
    params: dict[str, Any] | None = None,
) -> int:
    """Log a policy enforcement decision."""
    import json

    _ensure_policy_audit_table(db_url)
    conn = _get_conn(db_url)
    now = _now_iso()
    params_json = json.dumps(params) if params else None
    with _db_lock:
        cur = conn.execute(
            "INSERT INTO policy_audit_log "
            "(action_name, agent_id, decision, reason, "
            "tier, params_json, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                action_name,
                agent_id,
                decision,
                reason,
                tier,
                params_json,
                now,
            ),
        )
        conn.commit()
        return cur.lastrowid or 0


def list_policy_audit(
    db_url: str,
    *,
    limit: int = 100,
    action_name: str | None = None,
) -> list[dict[str, Any]]:
    """List recent policy audit entries."""
    _ensure_policy_audit_table(db_url)
    conn = _get_conn(db_url)
    lim = max(1, min(1000, int(limit or 100)))
    if action_name:
        rows = conn.execute(
            "SELECT * FROM policy_audit_log "
            "WHERE action_name = ? "
            "ORDER BY created_at DESC LIMIT ?",
            (action_name, lim),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM policy_audit_log " "ORDER BY created_at DESC LIMIT ?",
            (lim,),
        ).fetchall()
    return [dict(r) for r in rows]


def get_action_approval_queue_summary(db_url: str) -> dict[str, int]:
    conn = _get_conn(db_url)
    counts = {
        "pending": 0,
        "approved": 0,
        "rejected": 0,
        "executed": 0,
        "expired": 0,
    }
    with _db_lock:
        try:
            rows = conn.execute(
                "SELECT status, COUNT(*) AS c FROM action_approval_queue GROUP BY status"
            ).fetchall()
        except sqlite3.OperationalError:
            return {"total": 0, **counts}

    total = 0
    for row in rows:
        status = str(row["status"] or "").strip()
        count = int(row["c"] or 0)
        total += count
        if status in counts:
            counts[status] = count
    return {"total": total, **counts}


def get_policy_audit_summary(db_url: str) -> dict[str, Any]:
    _ensure_policy_audit_table(db_url)
    conn = _get_conn(db_url)
    decision_counts: dict[str, int] = {}
    with _db_lock:
        rows = conn.execute(
            "SELECT decision, COUNT(*) AS c FROM policy_audit_log GROUP BY decision"
        ).fetchall()

    total = 0
    for row in rows:
        decision = str(row["decision"] or "unknown").strip() or "unknown"
        count = int(row["c"] or 0)
        decision_counts[decision] = count
        total += count

    blocked_total = sum(
        decision_counts.get(decision_name, 0)
        for decision_name in ("blocked", "rejected", "denied")
    )
    return {
        "total": total,
        "allowed_total": decision_counts.get("allowed", 0),
        "blocked_total": blocked_total,
        "decision_counts": decision_counts,
    }
