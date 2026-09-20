"""Port the failed-goal-progress fix into the authority's live tree.

Gated: every anchor must match EXACTLY ONCE or nothing is written.

All 16,796 failed goal_plans rows also carry progress_pct = 100 and completed_at,
because the writer that marks a goal failed also asserted that it completed. The
100% is removed; completed_at is kept because autopilot.py queries
`status='failed' AND completed_at > ?`, so here the field means "terminal at".
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

BACKUP_DIR = Path(".runtime/deploy-backups/handport-goal-progress")

AW = Path("app/services/agent_worker.py")
AW_OLD = '''                    UPDATE goal_plans
                    SET status = 'failed', progress_pct = 100,
                        completed_at = ?, updated_at = ?
                    WHERE id = ?
'''
AW_NEW = '''                    UPDATE goal_plans
                    SET status = 'failed',
                        completed_at = ?, updated_at = ?
                    WHERE id = ?
'''

LS = Path("app/services/lifecycle_sweep.py")
LS_OLD = '''                f"""UPDATE goal_plans
                    SET status = 'failed',
                        progress_pct = 100,
                        completed_at = strftime(
'''
LS_NEW = '''                f"""UPDATE goal_plans
                    SET status = 'failed',
                        completed_at = strftime(
'''

EDITS = [
    ("agent-worker", AW, AW_OLD, AW_NEW),
    ("lifecycle-sweep", LS, LS_OLD, LS_NEW),
]


def main() -> int:
    texts = {p: p.read_text(encoding="utf-8") for _n, p, _o, _w in EDITS}

    problems = []
    for name, path, old, _new in EDITS:
        n = texts[path].count(old)
        if n != 1:
            problems.append(f"  {name}: anchor matched {n} time(s), need exactly 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    for _n, path, _o, _w in EDITS:
        shutil.copy2(path, BACKUP_DIR / path.name)
        print(f"backup {BACKUP_DIR / path.name}")

    for name, path, old, new in EDITS:
        before = texts[path]
        after = before.replace(old, new, 1)
        path.write_text(after, encoding="utf-8")
        print(
            f"{name}: {path} {len(before)} -> {len(after)} "
            f"sha {hashlib.sha256(after.encode()).hexdigest()[:12]}"
        )

    aw = AW.read_text(encoding="utf-8")
    ls = LS.read_text(encoding="utf-8")
    checks = [
        ("agent_worker no forced 100", "SET status = 'failed', progress_pct = 100," not in aw),
        ("agent_worker still terminal", "SET status = 'failed',\n                        completed_at" in aw),
        ("sweep no forced 100", "SET status = 'failed',\n                        progress_pct = 100," not in ls),
        ("sweep still terminal", "SET status = 'failed',\n                        completed_at" in ls),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing rolled back automatically: "
              + ", ".join(failed))
        return 1

    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
