"""One-time collapse of already-queued duplicate owner messages.

The dedup now in `enqueue_owner_message` stops new duplicates. This handles the
backlog that accumulated before it: 328 rows sitting `held`/`queued` that are only
158 distinct findings.

Non-destructive by construction:
  * no row is deleted, and no body is modified
  * the newest row of each duplicate group is KEPT and carries `repeat_count`
    (so the recurrence stays visible) and the group's newest timestamp
  * the older copies are marked `superseded` -- an existing status value, already
    used by 45 rows -- rather than removed, so the audit trail of when each was
    raised survives and the change is reversible by a status update

Also exercises the lazy column migration against the real 3 GB database, which is
the path that would otherwise only run on the next live enqueue.
"""

from __future__ import annotations

import sqlite3
import sys

sys.path.insert(0, ".")

from app.database import _ensure_owner_message_columns, _get_conn  # noqa: E402

DB_URL = "sqlite:///data/secretary.db"


def main() -> int:
    conn = _get_conn(DB_URL)
    conn.row_factory = sqlite3.Row

    print("=== before ===")
    before_rows = conn.execute(
        "SELECT COUNT(*) FROM owner_message_queue WHERE status IN ('held','queued')"
    ).fetchone()[0]
    before_distinct = conn.execute(
        "SELECT COUNT(*) FROM (SELECT DISTINCT reason, body FROM owner_message_queue "
        "WHERE status IN ('held','queued'))"
    ).fetchone()[0]
    print(f"  held/queued rows : {before_rows}")
    print(f"  distinct findings: {before_distinct}")
    print(f"  removable as duplicates: {before_rows - before_distinct}")

    # The migration the deployed code performs lazily; run it now so the backfill
    # can write repeat_count, and so it is proven on the real database.
    _ensure_owner_message_columns(DB_URL, conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(owner_message_queue)")}
    print(f"  columns now include repeat_count/last_seen_at: "
          f"{'repeat_count' in cols and 'last_seen_at' in cols}")

    groups = conn.execute(
        """SELECT reason, body, COUNT(*) AS n, MAX(created_at) AS newest
           FROM owner_message_queue
           WHERE status IN ('held','queued')
           GROUP BY reason, body HAVING COUNT(*) > 1"""
    ).fetchall()

    superseded = 0
    for g in groups:
        ids = [
            r["id"]
            for r in conn.execute(
                """SELECT id FROM owner_message_queue
                   WHERE reason = ? AND body = ? AND status IN ('held','queued')
                   ORDER BY created_at DESC""",
                (g["reason"], g["body"]),
            ).fetchall()
        ]
        keep, others = ids[0], ids[1:]
        conn.execute(
            """UPDATE owner_message_queue
               SET repeat_count = ?, last_seen_at = ?
               WHERE id = ?""",
            (g["n"], g["newest"], keep),
        )
        conn.executemany(
            "UPDATE owner_message_queue SET status = 'superseded' WHERE id = ?",
            [(i,) for i in others],
        )
        superseded += len(others)
        if g["n"] > 5:
            print(f"  {g['reason']}: {g['n']} rows -> 1 (repeat_count={g['n']})")
    conn.commit()

    print("=== after ===")
    after_rows = conn.execute(
        "SELECT COUNT(*) FROM owner_message_queue WHERE status IN ('held','queued')"
    ).fetchone()[0]
    print(f"  held/queued rows : {after_rows}")
    print(f"  collapsed this run: {superseded}")
    total_superseded = conn.execute(
        "SELECT COUNT(*) FROM owner_message_queue WHERE status = 'superseded'"
    ).fetchone()[0]
    print(f"  total 'superseded' status rows: {total_superseded}")
    print(f"  rows deleted: 0 (none — every row is still present)")
    print(f"  total rows in table: "
          f"{conn.execute('SELECT COUNT(*) FROM owner_message_queue').fetchone()[0]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
