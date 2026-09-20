"""Close the read snapshot before writing in owner-queue.py.

The defect: `_close` and `cmd_answer` both do

    row = con.execute("SELECT ... WHERE id=?", (a.id,)).fetchone()   # opens a read txn
    con.execute("UPDATE owner_decision_queue SET ... WHERE id=?", ...)  # upgrade -> BUSY

Python's sqlite3 opens a **deferred** transaction on the SELECT. The UPDATE then has
to upgrade a read transaction to a write one, and if any other connection committed
in between -- and the API writes to this database continuously -- SQLite returns
SQLITE_BUSY *immediately*. `timeout=20` cannot help, because waiting cannot make a
stale snapshot current; the transaction has to be started fresh.

Measured 2026-09-14: `owner-queue.py resolve` failed four times in a row with
`sqlite3.OperationalError: database is locked` before succeeding inside a retry loop.
This is the same defect, and the same one-line fix, already documented in
`app/services/dsh_session_ingest.py`.

Gated: both anchors must match exactly once or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "bin" / "owner-queue.py"
BACKUP = Path.home() / "bin" / "owner-queue.py.pre-snapshot-fix"

NOTE = '''
    # Close the read snapshot BEFORE writing. The SELECT above leaves a deferred
    # transaction open, so the UPDATE would have to upgrade a read transaction to a
    # write one -- and if any other connection committed in between (the API writes
    # to this database continuously) SQLite returns SQLITE_BUSY *immediately*.
    # `timeout=20` cannot help: waiting cannot make a stale snapshot current.
    # Measured 2026-09-14: resolve failed four times in a row before succeeding in a
    # retry loop. Same fix as app/services/dsh_session_ingest.py.
    con.commit()
'''

ANCHORS = [
    '    row = con.execute("SELECT id, status FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()\n',
    '    row = con.execute("SELECT 1 FROM owner_decision_queue WHERE id=?", (a.id,)).fetchone()\n',
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    for anchor in ANCHORS:
        n = text.count(anchor)
        if n != 1:
            print(f"REFUSING: anchor matched {n} times, need 1: {anchor.strip()[:70]}")
            return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    shutil.copy2(TARGET, BACKUP)

    new = text
    for anchor in ANCHORS:
        new = new.replace(anchor, anchor + NOTE, 1)

    if new.count("Close the read snapshot BEFORE writing") != 2:
        print("REFUSING: both sites were not patched")
        return 1
    if "def _close(" not in new or "def cmd_answer(" not in new:
        print("REFUSING: functions missing")
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PATCH APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
