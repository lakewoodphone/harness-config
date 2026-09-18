"""Port the ghost-agent fix and the missing code backup into the authority's
live checkout.

Evidence: a read-only reconciliation audit on 2026-09-14 found `error_log`
holding 69 `ghost_agent` rows (15 distinct messages), all unresolved, newest
2026-09-14T14:31:37Z, re-recorded every 6h. Root cause: the LLM invents
department names in the `delegate_task` tool call and nothing between that
parameter and `goal_plans.assigned_agent` validates them; only a reactive alias
dict cleans up afterwards. Amplifier: three `skipped` steps on CANCELLED plans
are treated as non-terminal, so 28,371 skipped goal_steps are rescanned every 10
minutes forever.

Same gate structure as the work-mode port: every anchor must match exactly once
or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

BACKUP_DIR = Path(".runtime/deploy-backups/handport-ghost")

# --------------------------------------------------------------------------
# 1. app/database.py -- the four alias entries
# --------------------------------------------------------------------------
DB = Path("app/database.py")
DB_OLD = '''    "dept_evolution": "dept_evolution_reliability",
}
'''
DB_NEW = '''    "dept_evolution": "dept_evolution_reliability",
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
}
'''

# --------------------------------------------------------------------------
# 2. app/services/self_healing_monitor.py -- stop rescanning cancelled plans
# --------------------------------------------------------------------------
MON = Path("app/services/self_healing_monitor.py")
MON_OLD = "                    WHERE status NOT IN ('completed','cancelled','failed')\n"
MON_NEW = (
    "                    WHERE status NOT IN ('completed','cancelled','failed','skipped')\n"
)

# --------------------------------------------------------------------------
# 3. app/workforce.py -- canonicalize at the single writer
# --------------------------------------------------------------------------
WF = Path("app/workforce.py")
WF_OLD = '''    if to_agent_id is None:
        to_agent_id = _auto_route_task(task, from_agent_id)

    # Update the task assignment
'''
WF_NEW = '''    if to_agent_id is None:
        to_agent_id = _auto_route_task(task, from_agent_id)

    # 2026-09-14: canonicalize BEFORE storing. The LLM invents department names
    # in the delegate_task tool call, and this function is the single writer that
    # turns them into rows; nothing between here and `assigned_to` validated
    # them, so the names landed raw and were then copied verbatim into
    # goal_plans.assigned_agent. Only the reactive alias dict in database.py
    # cleaned up afterwards -- which is exactly why the seven names patched on
    # 2026-08-31 stopped fireing and these four did not.
    from app.database import canonicalize_assignment_agent

    _canonical_target = canonicalize_assignment_agent(to_agent_id)
    if _canonical_target:
        to_agent_id = _canonical_target

    # Update the task assignment
'''

# --------------------------------------------------------------------------
# 4. scripts/server/backup-data.sh -- the code had no backup at all
# --------------------------------------------------------------------------
BK = Path("scripts/server/backup-data.sh")
BK_OLD = 'echo "Backup written to $OUT_DIR"\n'
BK_NEW = '''# ── 2026-09-14: the CODE had no backup of any kind ───────────────────────
# The runtime tarball above lists .env, data/* and .runtime ONLY. Nothing
# snapshotted app/, scripts/, tests/ or docs/, so the live checkout's source
# existed on exactly one disk. Found while auditing the deploy path: 11 tracked
# files carried bytes present in no git ref (local or remote), plus a commit on
# no branch, and a single disk failure would have lost them outright. Code is
# small; generated caches and databases are excluded.
tar --ignore-failed-read -czf "$OUT_DIR/personal-secretary-code.tgz" \\
  --exclude='__pycache__' --exclude='*.pyc' --exclude='node_modules' \\
  --exclude='.pytest_cache' --exclude='.mypy_cache' --exclude='.next' \\
  --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \\
  --exclude='*.sqlite3' --exclude='*.sqlite3-wal' --exclude='*.sqlite3-shm' \\
  app scripts tests docs src web deploy 2>/dev/null || true
echo "code backup: $(stat -c%s "$OUT_DIR/personal-secretary-code.tgz" 2>/dev/null || echo 0) bytes"

echo "Backup written to $OUT_DIR"
'''

EDITS = [
    ("database-aliases", DB, DB_OLD, DB_NEW),
    ("monitor-skipped", MON, MON_OLD, MON_NEW),
    ("workforce-canonicalize", WF, WF_OLD, WF_NEW),
    ("backup-code", BK, BK_OLD, BK_NEW),
]


def main() -> int:
    texts = {path: path.read_text(encoding="utf-8") for _n, path, _o, _w in EDITS}

    problems = []
    for name, path, old, _new in EDITS:
        n = texts[path].count(old)
        if n != 1:
            problems.append(f"  {name}: anchor matched {n} time(s), need exactly 1 ({path})")
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
            f"{name}: {path} {len(before)} -> {len(after)} bytes "
            f"sha {hashlib.sha256(after.encode()).hexdigest()[:12]}"
        )

    # post-conditions
    checks = [
        ("alias dept_home_and_life", '"dept_home_and_life": "dept_home_life"' in DB.read_text()),
        ("alias dept_personal", '"dept_personal": "dept_home_life"' in DB.read_text()),
        ("alias dept_ceo", '"dept_ceo": "orchestrator"' in DB.read_text()),
        ("alias dept_executive_assistant", '"dept_executive_assistant": "orchestrator"' in DB.read_text()),
        ("alias count grew", DB.read_text().count('": "') >= 20),
        ("skipped is terminal", "'failed','skipped')" in MON.read_text()),
        ("workforce canonicalizes", "canonicalize_assignment_agent" in WF.read_text()),
        ("code backup added", "personal-secretary-code.tgz" in BK.read_text()),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed after write: " + ", ".join(failed))
        return 1

    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
