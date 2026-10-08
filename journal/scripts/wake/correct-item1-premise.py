#!/usr/bin/env python3
"""Correct item #1's premise: the overload it was filed against is no longer present.

THE RULE THIS ENFORCES. An item is a statement about the world at the time it was filed. If the world
moved, the item must move with it, or the next shift investigates a ghost. The owner's own words apply:
"you should be really careful... don't do stupid work or the same work over and over."

MEASURED, and it is a real movement:
    filed 2026-09-28 18:32Z   load average 16.15 / 14.48 / 12.23 on FOUR cores; top consumers were a
                              2.49 GB python, a 600 MB python, node, and FIVE chrome processes;
                              `curl 127.0.0.1:8002/health` did NOT answer within 5 s.
    now     19:46Z            load average 1.69 / 2.97 / 3.98; top consumer is one python at 83 % CPU
                              (844 MB) and a sqlite3; `/health` returns 200 in 0.12 s.

So the AUTHORITY IS NO LONGER 4x OVERSUBSCRIBED, and the specific failure this item was raised for -
the ssh hop timing out and the whole wake/dispatch system dying silently with it - did not reproduce.
That does NOT mean the item is wrong; it means the measured condition has moved and the item must say
so, because a shift woken for it has to spend its first minutes discovering this. Two honest outcomes
are now possible and BOTH are acceptable: (a) verify it stays down and close the item as
no-longer-reproduced with the numbers, or (b) find what was loading it and make THAT durable, which is
the real work.

WHAT IS PRESERVED, because it is still an unfixed weakness: nothing PREVENTS the next overload. The
appetite is for a guard, not a post-mortem - that is the part worth doing, and it is now named in the
item so the shift starts from it.

Usage: python3 correct-item1-premise.py [--apply]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/home/zabz/work/work.db")
ITEM = 1
NOTE = (
    "\n\n=== PREMISE UPDATED 2026-09-28 19:46Z - READ THIS BEFORE INVESTIGATING ===\n"
    "The overload this item was filed against is NOT PRESENT NOW, measured:\n"
    "  filed 18:32Z : load 16.15/14.48/12.23 on 4 cores; a 2.49 GB python, a 600 MB python, node and\n"
    "                 FIVE chrome processes; `curl 127.0.0.1:8002/health` did not answer in 5 s.\n"
    "  now   19:46Z : load 1.69/2.97/3.98; top consumer one python at 83% (844 MB) plus a sqlite3;\n"
    "                 `/health` returns 200 in 0.12 s.\n"
    "So: do NOT re-derive the crisis. Two acceptable outcomes, both honest:\n"
    "  (a) confirm it stays down over three samples and close this item with the numbers, saying the\n"
    "      condition did not reproduce and what you checked;\n"
    "  (b) find what WAS loading it and make THAT durable - the real work here is that NOTHING PREVENTS\n"
    "      the next overload, and an ssh banner timeout takes the whole wake/dispatch system down with\n"
    "      no error that looks like a network error.\n"
    "The unfixed weakness is the GUARD, not the incident.\n")
DOD_ADD = (
    " UPDATED: the measurable proof is now (i) three load samples 5 minutes apart quoted, AND (ii) a "
    "stated guard that refuses or reports rather than adding work when the control plane is saturated - "
    "the guard is the deliverable, because the overload itself has already passed."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(str(DB), timeout=20)
    row = c.execute("SELECT id,priority,state,why,dod FROM work_item WHERE id=?", (ITEM,)).fetchone()
    if not row:
        print("no item #%d" % ITEM)
        return 1
    print("item #%d [%s] priority %s" % (row[0], row[2], row[1]))
    if NOTE.strip() in (row[3] or ""):
        print("already corrected")
        return 0
    if a.apply:
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(DB, str(DB) + ".bak-premise-" + stamp)
        c.execute("UPDATE work_item SET why=coalesce(why,'')||?, dod=coalesce(dod,'')||?, updated_at=? "
                  "WHERE id=?",
                  (NOTE, DOD_ADD, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), ITEM))
        c.commit()
        print("updated (backup %s.bak-premise-%s)" % (DB, stamp))
        got = c.execute("SELECT substr(why,-520) FROM work_item WHERE id=?", (ITEM,)).fetchone()[0]
        print("\n--- the new tail of `why`, as a shift will read it ---")
        print(got)
    else:
        print("dry run: would append %d chars to why and %d to dod" % (len(NOTE), len(DOD_ADD)))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
