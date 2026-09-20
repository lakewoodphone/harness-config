"""Port urgency="high" -> "urgent" for the sync-login notification.

Gated: the anchor must match exactly once.

Why: the attention-debt check counts `urgency == 'urgent'` exactly, and the badge
renders only that summary line. With "high" the row was stored, held and correctly
reasoned, and the owner saw nothing -- a stored row that moves no surface he opens
has not delivered.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-urgency.py.pre")

OLD = '''                reason=f"sync_needs_login:{name}",
                urgency="high",
                status="held",
'''

NEW = '''                reason=f"sync_needs_login:{name}",
                # "urgent", not "high": the attention-debt check counts
                # urgency == 'urgent' exactly, so a "high" row is stored and visible
                # in the table while the badge's summary line never moves.
                urgency="urgent",
                status="held",
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"REFUSING: anchor matched {n} time(s), need exactly 1")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)
    new = text.replace(OLD, NEW, 1)

    if 'urgency="high"' in new.split("_notify_owner_sync_needs_login")[1][:1200]:
        print("REFUSING: urgency=high still present in the helper")
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
