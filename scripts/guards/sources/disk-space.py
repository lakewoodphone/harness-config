#!/usr/bin/env python3
"""FLAG SOURCE: the authority's own disk, and the retention that bounds it.

THE SIGNAL
----------
`~/bin/disk-guard.py --json` measures free space on `/` and `/tmp`, checks that the backup
retention script exists and is executable, and (only when it is over threshold) reports where the
space went. Exit 0 below threshold, 1 at or above, 2 when it cannot read the filesystem.

WHY THIS SOURCE EXISTS, measured on `secratary`
-----------------------------------------------
    / at 100%, 17 MB free          2026-09-27   backups stopped; "there is NO valid backup" (P2553)
    / at 99%, 7.6 GB free          2026-09-30   secretary-backups 298 GB / 21 dirs, and the
                                                retention script had been deleted by a deployment
                                                whose caller only WARNED and carried on (P2799)

Two near-fills in four days, and the only disk check on the machine watched a DIFFERENT box daily.
One backup directory is ~18 GB, which is a fifth of the free space that existed on 2026-09-30 -- so
the check has to be more frequent than the growth, and it has to reach somebody.

PRIORITY  high at or above the critical threshold, normal at warn. A full root filesystem does not
          fail loudly: SQLite raises on write, and the family chat and the company database both
          write there.

SUBJECTS  disk-space:<pct bucket>  -- bucketed to the threshold crossed, so a disk that stays at
          91% does not re-file every fifteen minutes, and a disk that moves from 91% to 96% does.

MUST NEVER
    - fire below the threshold (a source that fires on the healthy case has failed);
    - delete, move or truncate anything. This files work; the FIX, including any deletion, belongs
      to the session that claims it, and deleting backups beyond the documented F7 policy is the
      owner's call, not a source's.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "disk-space"
GUARD = Path(os.environ.get("DISK_GUARD", str(Path.home() / "bin" / "disk-guard.py")))
COOLDOWN_SECONDS = int(os.environ.get("DISK_SPACE_COOLDOWN", "10800"))  # 3 h


def _report() -> dict:
    if not GUARD.is_file():
        raise Unreadable("the disk guard itself is missing at %s" % GUARD)
    try:
        p = subprocess.run([sys.executable or "python3", str(GUARD), "--json", "--write-status"],
                           capture_output=True, text=True, timeout=300)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not run the disk guard: %s" % exc)
    raw = (p.stdout or "").strip()
    if not raw:
        raise Unreadable("the disk guard printed nothing (rc=%s, stderr=%s)"
                         % (p.returncode, (p.stderr or "").strip()[:200]))
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("the disk guard output is not JSON: %s" % exc)


def collect(args) -> list[Finding]:
    r = _report()
    if r.get("unreadable"):
        raise Unreadable("the disk guard could not stat the root filesystem")
    findings = r.get("findings") or []
    if not findings:
        return []

    root = r.get("root") or {}
    pct = root.get("used_pct", 0)
    critical = pct >= float(r.get("crit_pct", 95))
    bucket = int(pct // 5) * 5

    consumers = "\n".join("       %8d MB  %s" % (c["mb"], c["path"])
                          for c in (r.get("consumers") or []))

    prompt = (
        "THE AUTHORITY'S ROOT FILESYSTEM IS OVER ITS THRESHOLD. This is the second time in four\n"
        "days: on 2026-09-27 it reached 100%% (17 MB free) and the backups stopped; on 2026-09-30 it\n"
        "reached 99%% (7.6 GB free) with 298 GB of backups held by a retention script that a\n"
        "deployment had deleted. A full root filesystem does not fail loudly -- SQLite raises on\n"
        "write, and the company database and the family chat both live there.\n\n"
        "MEASURED NOW (%s)\n"
        "    /     %s%% used, %s MB free of %s MB\n"
        "    /tmp  %s%% used\n"
        "    backup root: %s directories, %s MB\n"
        "    retention script %s\n"
        "    findings:\n        %s\n"
        "%s\n\n"
        "WHAT TO DO, in order, and nothing here is a sweep:\n"
        "  1. READ the retention policy before deleting anything. It is written down in\n"
        "     `scripts/server/prune-backups.sh` as F7 (2026-08-30): keep everything under 1 day old,\n"
        "     then one per day for 1-7 days, one per week for 7-30 days, nothing older than 30 days.\n"
        "     If the script is present, `prune-backups.sh /home/zabz/secretary-backups --dry-run`\n"
        "     says exactly what it would remove. Apply it and report the freed space.\n"
        "  2. IF THE RETENTION SCRIPT IS MISSING, THAT IS THE FAULT. Restore it (it is tracked in\n"
        "     the repo; `git log --all --oneline --source -1 -- scripts/server/prune-backups.sh`\n"
        "     finds the newest copy), then prove it by running it --dry-run. Do not delete backups by\n"
        "     hand to compensate for a missing script: that is how the policy gets lost.\n"
        "  3. SAFE RECLAIM that needs no policy decision, biggest first: stale git worktrees\n"
        "     (`git worktree list` / `git worktree prune`), `_pt_*` / `__pycache__` test artifacts\n"
        "     inside the repo (`agent-fleet clean`), and dated scratch under /tmp older than two\n"
        "     days with nothing holding it open (`lsof +D /tmp` first).\n"
        "  4. NEVER delete a backup directory beyond the F7 policy without the owner saying so in\n"
        "     this conversation. Backups are the one thing here whose loss is irreversible.\n"
        "  5. Prove the fix with `python3 ~/bin/disk-guard.py` and paste its first line.\n\n"
        "Then say what is still growing, because a disk that fills twice in four days has a cause\n"
        "and the cause is not the number.") % (
        r.get("at"), root.get("used_pct"), root.get("free_mb"),
        int(root.get("total_bytes", 0) // 1048576),
        (r.get("tmp") or {}).get("used_pct"), r.get("backup_dirs"), r.get("backup_mb"),
        ("PRESENT" if (r.get("retention") or {}).get("exists") else "MISSING"),
        " | ".join(findings), consumers)

    return [Finding(
        subject="disk-space:%d" % bucket,
        prompt=prompt,
        priority="high" if critical else "normal",
        kind="repair",
        context=json.dumps({"at": r.get("at"), "used_pct": pct,
                            "free_mb": root.get("free_mb"),
                            "backup_dirs": r.get("backup_dirs"),
                            "backup_mb": r.get("backup_mb"),
                            "retention_exists": (r.get("retention") or {}).get("exists"),
                            "findings": findings}),
        cooldown_seconds=COOLDOWN_SECONDS,
    )]


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
