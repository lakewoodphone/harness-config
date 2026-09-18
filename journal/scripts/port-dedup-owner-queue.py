"""Hand-port the owner-queue dedup into the authority's live checkout.

Same gate as the other ports: every anchor must match EXACTLY ONCE or the script
refuses and writes nothing. Needed because the authority's deploy.sh cannot run
on its diverged checkout.

Three surgical edits rather than whole-function replacement, so the live file's
own docstring wording is left as it is:
  1. the CREATE TABLE gains repeat_count / last_seen_at
  2. a lazy, idempotent column migration is inserted before enqueue_owner_message
  3. the INSERT becomes dedup-then-insert
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/database.py")
BACKUP = Path(".runtime/deploy-backups/handport-dedup.py.pre")

CREATE_OLD = """            CREATE TABLE IF NOT EXISTS owner_message_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                reason TEXT DEFAULT '',
                urgency TEXT DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                sent_at TEXT
            );
"""
CREATE_NEW = """            CREATE TABLE IF NOT EXISTS owner_message_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                reason TEXT DEFAULT '',
                urgency TEXT DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                sent_at TEXT,
                repeat_count INTEGER DEFAULT 1,
                last_seen_at TEXT
            );
"""

HELPER = '''_OWNER_MSG_COLUMNS_ENSURED: set[str] = set()


def _ensure_owner_message_columns(db_url: str, conn) -> None:
    """Add repeat_count / last_seen_at to owner_message_queue if absent.

    SQLite has no ADD COLUMN IF NOT EXISTS, and CREATE TABLE IF NOT EXISTS does
    not add columns to a table that already exists -- so the dedup below would
    raise 'no such column' on every pre-existing database, including the
    authority's 3 GB one. This makes the migration lazy, idempotent and cached
    per database URL.
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
        conn.commit()
    _OWNER_MSG_COLUMNS_ENSURED.add(db_url)


'''

DEF_OLD = "def enqueue_owner_message(\n"
DEF_NEW = HELPER + "def enqueue_owner_message(\n"

INSERT_OLD = """    with _db_lock:
        cur = conn.execute(
            \"\"\"INSERT INTO owner_message_queue
               (body, reason, urgency, status, created_at)
               VALUES (?, ?, ?, ?, ?)\"\"\",
            (body, reason, urgency, status_value, now),
        )
        conn.commit()
        return cur.lastrowid or 0
"""

INSERT_NEW = '''    # Dedup against an identical undelivered message (added 2026-09-14).
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
        existing = conn.execute(
            """SELECT id FROM owner_message_queue
               WHERE reason = ? AND body = ? AND status IN ('held', 'queued')
               ORDER BY created_at DESC LIMIT 1""",
            (reason, body),
        ).fetchone()
        if existing is not None:
            conn.execute(
                """UPDATE owner_message_queue
                   SET repeat_count = COALESCE(repeat_count, 1) + 1,
                       last_seen_at = ?
                   WHERE id = ?""",
                (now, existing["id"]),
            )
            conn.commit()
            return int(existing["id"])
        cur = conn.execute(
            """INSERT INTO owner_message_queue
               (body, reason, urgency, status, created_at, repeat_count, last_seen_at)
               VALUES (?, ?, ?, ?, ?, 1, ?)""",
            (body, reason, urgency, status_value, now, now),
        )
        conn.commit()
        return cur.lastrowid or 0
'''

EDITS = [
    ("create-table", CREATE_OLD, CREATE_NEW),
    ("helper", DEF_OLD, DEF_NEW),
    ("dedup-insert", INSERT_OLD, INSERT_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  anchor {name!r} matched {n} time(s), need exactly 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text
    for _n, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    checks = [
        ("repeat_count in DDL", "repeat_count INTEGER DEFAULT 1" in new),
        ("last_seen_at in DDL", "last_seen_at TEXT" in new),
        ("migration defined", "def _ensure_owner_message_columns(" in new),
        ("migration called", "_ensure_owner_message_columns(db_url, conn)" in new),
        ("dedup select present", "WHERE reason = ? AND body = ?" in new),
        ("repeat bump present", "repeat_count = COALESCE(repeat_count, 1) + 1" in new),
        ("old blind insert gone", INSERT_OLD not in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 before: {before}")
    print(f"sha256 after:  {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"bytes: {len(text)} -> {len(new)}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
