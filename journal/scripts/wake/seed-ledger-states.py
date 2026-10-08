#!/usr/bin/env python3
"""Write a seed state file for every ledger-only project that lacks one.

WHY: the keepalive source requires a readable per-project signal, and refuses to file anything
for a project whose state file is missing - which is CORRECT for a project that keeps its own
state and the wrong answer for one whose state is the ledger. Measured 2026-09-28: after
registering all nine projects, the dry run stopped at
    SIGNAL UNREADABLE -- project 'lpt-sync': no state file
so six of the owner's named projects would have stayed permanently silent while looking
properly configured. The seed says exactly that and nothing more: `ledger_only: true`, and the
ledger named as the authoritative place.

Usage: python3 seed-ledger-states.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

REG = Path("/home/zabz/bin/sources/projects.json")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    doc = json.loads(REG.read_text(encoding="utf-8"))
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    wrote = 0
    for row in doc["projects"]:
        sf = row.get("state_file")
        if not sf:
            continue
        p = Path(sf)
        if p.exists():
            continue
        p.parent.mkdir(parents=True, exist_ok=True)
        body = {
            "project": row["id"],
            "work_remaining": True,
            "remaining": ["not yet seeded: the first shift claims its item from the ledger"],
            "ledger_only": bool(row.get("ledger_only")),
            "note": ("The authoritative state for this project is the work ledger "
                     "(python3 ~/bin/work.py list --project %s). This file exists so the "
                     "keepalive source has a signal to read; it does not own the work." % row["id"]),
            "seeded_at": now,
        }
        if a.apply:
            p.write_text(json.dumps(body, indent=2) + "\n", encoding="utf-8")
            print("seeded %s" % p)
            wrote += 1
        else:
            print("would seed %s" % p)
    print("%d file(s) %s" % (wrote, "written" if a.apply else "to write"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
