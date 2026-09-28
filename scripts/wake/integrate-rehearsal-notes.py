#!/usr/bin/env python3
"""Put the rehearsal's findings into item #17, so the shift does not rediscover them or misread them.

WHAT THE REHEARSAL FOUND (in a throwaway worktree on the authority, 2026-09-28):
  * `origin/agent/windows-broker-channel` is 1 commit ahead of the point it was cut from.
  * `origin/main` has moved 48 commits AHEAD of that point since - other work landed meanwhile.
  * `git diff --diff-filter=D --name-only origin/main..origin/agent/windows-broker-channel` reports
    39 DELETED files. THAT NUMBER IS A TRAP, not a finding: it is the diff between two divergent
    histories, and 36 of those "deletions" are files the base gained after the branch was cut.
  * THE MERGE ITSELF IS CLEAN: `git merge --no-ff` staged 15 files with ZERO conflicts, and
    `git diff --cached --diff-filter=D --name-only` - the guard the definition of done actually names -
    is EMPTY.

WHY THIS MATTERS ENOUGH TO WRITE DOWN. A shift reading only the branch-to-base diffstat would see
"39 files deleted, 13636 deletions" and refuse to merge, or would merge and panic. The distinguishing
test is not the diffstat; it is the merge's own staged result. This system has already lost 19,296
lines to a careless merge, so a guard that fires on the WRONG measurement is not caution - it is how
real work gets abandoned.

So this rewrites item #17's definition of done to carry the measured facts and the exact commands,
and says plainly which number to trust. The tests still have to run on the desktop: dotnet is NOT
installed on the authority, so the merge rehearsal could not run them.

Usage: python3 integrate-rehearsal-notes.py [--apply]
"""
from __future__ import annotations

import argparse
import shutil
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

DB = Path("/home/zabz/work/work.db")
ITEM = 17

DOD = (
    "MEASURED IN REHEARSAL 2026-09-28 (throwaway worktree on the authority, nothing merged):\n"
    "  base origin/main = 5afd6e3, ref = 72e8daf, ref is 1 commit ahead of where it was cut, the base "
    "has moved 48 commits since.\n"
    "  A TRAP TO KNOW ABOUT: `git diff --diff-filter=D --name-only origin/main..origin/agent/"
    "windows-broker-channel` reports 39 deleted files. THAT IS THE WRONG MEASUREMENT - most of them "
    "are files the base GAINED after the branch was cut. Do not refuse the merge because of it.\n"
    "  THE MERGE ITSELF WAS REHEARSED AND IS CLEAN: `merge --no-ff` staged 15 files, 0 conflicts, and "
    "the real guard `git diff --cached --diff-filter=D --name-only` is EMPTY.\n"
    "STEPS:\n"
    "  1) work in a worktree or a clone, never in the shared checkout: "
    "`git worktree add --detach /tmp/int-17 origin/main`\n"
    "  2) `git merge --no-ff origin/agent/windows-broker-channel` - expect NO conflicts\n"
    "  3) CONFIRM THE GUARD ON THE MERGE RESULT, not on the branch diff: "
    "`git diff --cached --diff-filter=D --name-only` must be EMPTY\n"
    "  4) run the tests ON THE DESKTOP (dotnet is NOT installed on the authority): "
    "`dotnet test windows/FilterService.Tests/KosherFilterService.Tests.csproj --nologo` - quote the "
    "result line; the branch's author measured Passed 112 / Total 119 against a baseline of 93\n"
    "  5) push the merged main (or the integration branch) and remove the worktree\n"
    "  6) close this item with the test result line and the empty guard as the proof"
)

WHY = (
    "the branch a shift created on 2026-09-28 is finished work that nothing merges, and the next shift "
    "would redo it. Rehearsed clean on 2026-09-28: 0 conflicts, 0 deletions in the merge result. The "
    "39-file diffstat against the base is the WRONG measurement and is documented in the definition of "
    "done so nobody refuses real work over it."
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(str(DB), timeout=20)
    row = c.execute("SELECT id, title, state FROM work_item WHERE id=?", (ITEM,)).fetchone()
    if not row:
        print("no item #%d" % ITEM)
        return 1
    print("item #%d [%s] %s" % (row[0], row[2], row[1]))
    if not a.apply:
        print("dry run: would rewrite dod (+%d chars) and why" % len(DOD))
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(DB, str(DB) + ".bak-rehearsal-" + stamp)
    c.execute("UPDATE work_item SET dod=?, why=?, updated_at=? WHERE id=?",
              (DOD, WHY, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), ITEM))
    c.commit()
    print("updated (backup %s.bak-rehearsal-%s)" % (DB, stamp))
    got = c.execute("SELECT substr(dod,1,180) FROM work_item WHERE id=?", (ITEM,)).fetchone()[0]
    print("dod now begins: %s..." % got.replace("\n", " ")[:170])
    c.close()

    print("\n=== what a shift takes first ===")
    p = subprocess.run(["python3", "/home/zabz/bin/work.py", "next"], capture_output=True, text=True)
    print(p.stdout.strip()[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
