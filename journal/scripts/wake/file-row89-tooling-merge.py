#!/usr/bin/env python3
"""Correct a session's overstatement about owner row 89, and file the work that row actually names.

WHAT THE SESSION SAID, in its evidence for dropping item #33:
    "the divergence was already raised as owner row 89 and closed 2026-09-18 with DECISION RECORDED:
     leave master alone; merge only the tooling files as engineering. So this is NOT a live owner
     decision."

WHAT ROW 89 ACTUALLY SAYS, read from the queue:
    status       : dismissed
    question     : "...Do you want the per-domain merge done now, or master left alone with the
                    corrected sync tooling on its rescue branch?"
    recommendation: "Leave master alone for now..."          <- a RECOMMENDATION, not an answer
    resolution   : "NO LIVE OWNER DECISION. Verified real by me on the authority 2026-09-18..."

So the OVERSTATEMENT is real and it matters: the session treated the system's own recommendation as the
owner's decision. Its other three conclusions hold and are good work - no commit is missing from the
remotes (a genuine finding), HEAD is on the remote, and no duplicate owner row was filed. But a
dismissed row is not an answered enquiry, and the difference is exactly the kind of thing this system
has been burned by ("the most expensive failures in this system's history were confident errors").

WHY THIS IS NOT PEDANTRY. If "a recommendation nobody answered" can be read as "he decided", then any
unanswered question becomes invisible forever - which is the failure mode the owner named when he
described problems that "just vanish". The rule: a row is answered when it carries his words, not when
it carries a recommendation.

AND THE WORK ROW 89 NAMES HAS NEVER BEEN FILED: taking the sync tooling from the authority side
(app/services/lpt_hub_sync.py, scripts/lpt-sync-to-production.py). A recommendation that is never
executed is worse than no recommendation, because it looks handled. This files it.

Usage: python3 file-row89-tooling-merge.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys

WORK = "/home/zabz/bin/work.py"
ITEM = 33
CORRECTION = (
    "\n\n=== CORRECTED 2026-09-28 19:50Z BY THE MANAGER - READ THIS FIRST ===\n"
    "This item was DROPPED with the reasoning that row 89 was 'closed 2026-09-18 with DECISION\n"
    "RECORDED'. That is an OVERSTATEMENT and it is corrected here: row 89's own status is `dismissed`\n"
    "and its own text says 'NO LIVE OWNER DECISION' - what it carries is a RECOMMENDATION ('Leave\n"
    "master alone for now'), not the owner's answer. A recommendation nobody answered is not a\n"
    "decision, and treating one as the other makes an unanswered question invisible forever.\n"
    "WHAT HOLDS FROM THE ORIGINAL REASONING, and it is good work: (a) zero commits reachable from HEAD\n"
    "are absent from every remote ref - nothing is lost; (b) HEAD is an ancestor of\n"
    "origin/authority-20260928; (c) no duplicate owner row was filed; (d) no branch was moved and no\n"
    "service restarted.\n"
    "WHAT REMAINS OPEN: the tooling-only merge row 89 recommends (app/services/lpt_hub_sync.py and\n"
    "scripts/lpt-sync-to-production.py, taking the authority side), now filed as its own item; and the\n"
    "question of whether to put row 89 back to the owner as a REAL question rather than leave it\n"
    "dismissed.\n")

DOD = (
    "1) In a WORKTREE of /home/zabz/personal-secretary-mvp (never the live checkout - the service runs "
    "from it), take the authority side of exactly the two files row 89 names: "
    "app/services/lpt_hub_sync.py and scripts/lpt-sync-to-production.py. "
    "2) `git diff` each against the current live copy and quote the change; if they are already "
    "identical, say so and this item closes as nothing-to-do. "
    "3) Do NOT touch the 70 personal-insurance documents or the 7 family-chat files - row 89 says "
    "explicitly that personal records must not be resolved by a tool default. "
    "4) Run whatever check the sync tooling itself provides and quote its result line. "
    "5) Push the result as a BRANCH, never to master. "
    "6) Close with the diff and the check output as proof. If master must not be touched to complete "
    "this, say so and leave the work on the branch.")

WHY = (
    "owner row 89 recommends a tooling-only merge the owner has not answered, and the work it names has "
    "never been filed - so a recommendation that was never executed looks handled. Row 89's own status "
    "is `dismissed` with 'NO LIVE OWNER DECISION', so this does not wait on him: taking the authority "
    "side of two named tooling files is ordinary engineering, and the branch is the safe shape.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    import sqlite3
    c = sqlite3.connect("/home/zabz/work/work.db", timeout=20)
    row = c.execute("SELECT why FROM work_item WHERE id=?", (ITEM,)).fetchone()
    if row and CORRECTION.strip() not in (row[0] or ""):
        if a.apply:
            c.execute("UPDATE work_item SET why=coalesce(why,'')||? WHERE id=?", (CORRECTION, ITEM))
            c.commit()
            print("corrected the record on item #%d (it stays dropped; the reasoning is now accurate)" % ITEM)
        else:
            print("would correct item #%d" % ITEM)
    c.close()

    cmd = ["python3", WORK, "add", "--project", "prod-db-sync",
           "--title", "Execute owner row 89's tooling-only merge: take the authority side of lpt_hub_sync.py and lpt-sync-to-production.py",
           "--dod", DOD, "--why", WHY, "--priority", "2", "--source", "row89"]
    if a.apply:
        p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=120)
        out = (p.stdout or "").strip()
        print("filed: %s" % out)
        m = re.search(r'"id":\s*(\d+)', out)
        if m:
            q = subprocess.run(["python3", WORK, "show", m.group(1)], capture_output=True,
                               text=True, encoding="utf-8", errors="replace", timeout=90)
            print("\n" + (q.stdout or "")[:700])
    else:
        print("dry run: would file the row-89 tooling item")
    return 0


if __name__ == "__main__":
    sys.exit(main())
