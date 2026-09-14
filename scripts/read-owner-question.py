"""Read one owner-decision-queue row in full, with a busy timeout.

Kept as a script rather than an inline -c so the quoting cannot corrupt it, and
with a busy_timeout because the authority's API holds the SQLite write lock in
bursts -- the queue CLI's plain connect() fails with 'database is locked' while
that happens.
"""

from __future__ import annotations

import json
import sqlite3
import sys

DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"


def main() -> int:
    row_id = int(sys.argv[1]) if len(sys.argv) > 1 else 19
    conn = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    row = conn.execute(
        "SELECT * FROM owner_decision_queue WHERE id = ?", (row_id,)
    ).fetchone()
    if row is None:
        print(f"no row {row_id}")
        return 2
    d = dict(row)
    print(f"ID {d['id']}   severity={d.get('severity')}   asked={d.get('asked_at')}   status={d.get('status')}")
    print(f"BLOCKS: {d.get('blocks')}")
    print()
    print("QUESTION:")
    print(d.get("question"))
    print()
    print("CONTEXT:")
    print(d.get("context"))
    print()
    opts = d.get("options_json")
    if opts:
        try:
            print("OPTIONS:")
            for i, o in enumerate(json.loads(opts), 1):
                print(f"  {i}. {o}")
        except Exception:
            print("OPTIONS:", opts)
    print()
    print("RECOMMENDATION:")
    print(d.get("recommendation"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
