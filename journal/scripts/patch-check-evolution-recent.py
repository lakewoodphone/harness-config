"""Bound check_evolution's duplicate scan to recent rows so the alarm can clear.

After the previous patch the summary is accurate -- it no longer claims "72
proposals unapplied", because auto-apply is off by configuration -- but the severity
stays HIGH because of the 38 duplicate offers already sitting in `evolution_log`.
Those rows are history: W57 stopped the engine manufacturing more of them, and no
code change can alter a logged row. So the alarm is pinned HIGH forever by its own
past, which is the same failure as the false alarm it replaced, one layer down.

A check that cannot clear after the fix lands is indistinguishable from a check that
is broken. The duplicate scan is now bounded to the last 7 days, so:
  * no new duplicates in a week -> the check clears itself;
  * duplicates return -> the count climbs and the alarm returns.

7 days is chosen against the observed rate: 38 offers for one file accumulated inside
the window that produced them, so a week is long enough to catch a recurrence and
short enough to clear.

Gated: the anchor must match exactly once.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path.home() / "ceo-kernel" / "ck" / "sentinel.py"
BACKUP = Path.home() / "ceo-kernel" / ".runtime" / "check-evolution-recent.py.pre"

DUP_OLD = '''    dup = sources.rows(
        "SELECT files_changed, COUNT(*) AS n FROM evolution_log WHERE applied=0 "
        "GROUP BY files_changed ORDER BY n DESC LIMIT 5",
        name="evolution_duplicates",
    )
'''

DUP_NEW = '''    # Bounded to the last 7 days on purpose. Historical duplicates are history: no
    # code change can alter a logged row, so scanning all of them pins this check
    # HIGH forever and makes it indistinguishable from a broken check. Bounded, it
    # clears itself once the engine stops producing duplicates, and returns if they
    # come back.
    dup = sources.rows(
        "SELECT files_changed, COUNT(*) AS n FROM evolution_log WHERE applied=0 "
        "AND created_at > datetime('now', '-7 days') "
        "GROUP BY files_changed ORDER BY n DESC LIMIT 5",
        name="evolution_duplicates",
    )
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    n = text.count(DUP_OLD)
    if n != 1:
        print(f"REFUSING: anchor matched {n} times, need exactly 1")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    new = text.replace(DUP_OLD, DUP_NEW, 1)

    checks = [
        ("window applied", "datetime('now', '-7 days')" in new),
        ("still groups by file", "GROUP BY files_changed" in new),
        ("auto-apply gate intact", "_auto_apply_enabled()" in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PATCH APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
