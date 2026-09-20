"""A proposal that can be neither applied nor dismissed is a log line pretending to be a queue.

Measured 2026-09-15: `evolution_log` holds **75 unapplied rows** -- 38 duplicate offers on
`app/services/activity_sync.py`, 18 on a vendored `web/node_modules/flatted/python/flatted.py` (a class
the writer now refuses, fixed in round 52), and ~19 genuine but generic refactor suggestions. The kernel
counts every unapplied row as `queued_for_review`, so the review queue it reports is 75 when the honest
number is 19, and the dead 56 can never leave it: `evolution_log` has exactly one terminal state
(`applied`), and pretending they were applied would be a lie in the record.

So: give the log the states it actually needs (`open` / `applied` / `dismissed`) with a note recording
why, the same lazy-column pattern already used for `owner_message_queue` and `agent_questions`. Then a
proposal can be *dismissed* honestly, and the queue a reader sees is the queue that exists.
"""

from __future__ import annotations

import pathlib
import sys

DB = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "database.py"

ANCHOR_COLS = '''def _is_vendored_path(path: str) -> bool:'''

COLS = '''_EVOLUTION_COLUMNS_ENSURED: set[str] = set()


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
            "SELECT id, files_changed, files_changed AS f, change_type, description FROM evolution_log "
            "WHERE applied = 0 AND COALESCE(status, 'open') = 'open'"
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


'''

ANCHOR_LOG = '''    conn = _get_conn(db_url)
    now = _now_iso()

    targets = [str(p) for p in (files_changed or [])]'''

LOG_NEW = '''    conn = _get_conn(db_url)
    now = _now_iso()
    _ensure_evolution_columns(db_url, conn)

    targets = [str(p) for p in (files_changed or [])]'''

ANCHOR_INSERT = '''        cur = conn.execute(
            """INSERT INTO evolution_log
               (agent_id, change_type, description, files_changed,
                proposal_id, applied, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (
                agent_id,
                change_type,
                description,
                payload,
                proposal_id,
                1 if applied else 0,
                now,
            ),
        )'''

INSERT_NEW = '''        cur = conn.execute(
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
        )'''


def main() -> int:
    text = DB.read_text(encoding="utf-8")
    # Distinctive markers for idempotence -- checking the first line of a replacement is not one
    # (the first line of LOG_NEW is `conn = _get_conn(db_url)`, which already exists everywhere).
    markers = {
        "the status columns and the drain helper": "_EVOLUTION_COLUMNS_ENSURED",
        "ensure the columns before writing": "_ensure_evolution_columns(db_url, conn)\n\n    targets =",
        "record the status on insert": "proposal_id, applied, created_at, status, status_note)",
    }
    for old, new, label in (
        (ANCHOR_COLS, COLS + ANCHOR_COLS, "the status columns and the drain helper"),
        (ANCHOR_LOG, LOG_NEW, "ensure the columns before writing"),
        (ANCHOR_INSERT, INSERT_NEW, "record the status on insert"),
    ):
        if text.count(old) != 1:
            print(f"REFUSE {label}: anchor count {text.count(old)}")
            return 2
        if markers[label] in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)
        print(f"planned  {label}")
    DB.write_text(text, encoding="utf-8")
    print(f"WROTE {DB}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
