#!/usr/bin/env python3
"""Remove the ambiguity in the integration definition of done: push the BRANCH, never main.

MY OWN INCONSISTENCY, spotted by reading what shifts actually did. The rehearsal notes for item #17
said, of the merged result: "The integration branch is local to the authority; promoting it into main
is a publishing decision for the owner." A shift reading that finishes the work and then STOPS to ask -
which is the exact failure mode this whole system exists to end ("8.9% of turns were me saying keep
going"). Meanwhile the canonical step list already says "push the merged main (or the integration
branch)", which contradicts it.

The rule that is both safe and unambiguous:
  * a shift PUSHES the integration BRANCH - that is ordinary, reversible and expected;
  * a shift NEVER promotes it into main - that is the owner's call;
  * a shift does not stop to ask, because the instruction now names exactly what to do.

This rewrites any open integration item whose definition of done still carries the old
"promoting it into main is a decision for the owner" wording so the two statements agree.

Usage: python3 fix-integration-push-rule.py [--apply]
"""
from __future__ import annotations

import argparse
import re
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/home/zabz/work/work.db")
OLD_RE = re.compile(r"[^.]*promoting it into main is (?:a publishing )?decision(?:s)? for the owner[^.]*\.",
                    re.I)
NEW = ("PUSH THE INTEGRATION BRANCH - that is expected and reversible. NEVER promote it into main: "
       "that decision belongs to the owner, and your job is to leave the branch ready for it. Do not "
       "stop to ask.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(str(DB), timeout=20)
    c.row_factory = sqlite3.Row
    rows = c.execute("SELECT id, project, dod, why FROM work_item "
                     "WHERE source='integrator' AND state IN ('todo','running') ORDER BY id").fetchall()
    touched = []
    for r in rows:
        dod = r["dod"] or ""
        m = OLD_RE.search(dod)
        if not m:
            continue
        new_dod = OLD_RE.sub(NEW, dod, count=1)
        # also make sure the push step is explicit if it is missing
        if "PUSH THE INTEGRATION BRANCH" not in new_dod:
            new_dod += ("\n6) push the integration branch (`git push -u origin integrate/...`) and close "
                        "this item with the test result line and the empty guard as the proof")
        touched.append((r["id"], r["project"]))
        if a.apply:
            c.execute("UPDATE work_item SET dod=?, updated_at=? WHERE id=?",
                      (new_dod, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), r["id"]))
    if a.apply and touched:
        c.commit()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(DB, str(DB) + ".bak-pushrule-" + stamp)
        print("backup: %s.bak-pushrule-%s" % (DB, stamp))
    c.close()
    for i, p in touched:
        print("  #%-3d %-18s dod clarified" % (i, p))
    print("\n%d item(s) %s" % (len(touched), "updated" if a.apply else "would be updated"))
    if not touched:
        print("no item still carries the ambiguous wording")
    return 0


if __name__ == "__main__":
    sys.exit(main())
