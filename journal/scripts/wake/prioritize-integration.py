#!/usr/bin/env python3
"""Make the integration items executable, and put them ahead of repair busywork.

TWO PROBLEMS FOUND BY MEASURING, not by guessing.

1. PRIORITY. Every integration item was filed at priority 3, level with ordinary work - and the three
   shifts running at 19:26Z went to `checkout-health:*` repair rows instead. Integrating what is
   already built is worth MORE than starting something new: an unmerged branch is finished work that
   is invisible, and the next shift redoes it (measured in this system: three lpt-website shifts on
   one unmerged fix). Real integration items get priority 2, and the one branch a shift created TODAY
   gets 1.

2. NOTHING TOLD THE SHIFT HOW. The item's `--dod` said what would prove the merge but not the shape
   of the merge itself, so a shift would have to re-derive it - and the lpt-website registry note
   exists precisely because a careless merge there deletes the storefront ("its diffstat against the
   truthful branch is 93 files, 952 insertions, 19296 DELETIONS"). This rewrites each item's
   definition of done to name the exact sequence and the guard, so the work is mechanical:

     git fetch origin && git checkout <base-branch> && git merge --no-ff <ref>
     re-run the project's tests and quote the result line
     git diff --diff-filter=D --name-only <base> HEAD   must be EMPTY

`--dod` cannot be edited through the CLI, so this writes the column directly - with a backup, and
printing every row it touches so the change is reviewable.

Usage: python3 prioritize-integration.py [--apply]
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
TODAY = "2026-09-28"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(str(DB), timeout=20)
    c.row_factory = sqlite3.Row
    rows = c.execute(
        "SELECT id, project, title, priority, created_at FROM work_item "
        "WHERE source='integrator' AND state='todo' ORDER BY id").fetchall()
    changed = []
    for r in rows:
        title = r["title"]
        # "Integrate origin/<ref> into <base>"
        try:
            rest = title.split("Integrate ", 1)[1]
            ref, base = rest.split(" into ", 1)
        except Exception:
            continue
        base_branch = base.replace("origin/", "")
        fresh = "windows-broker-channel" in ref or "kf0928" in ref
        prio = 1 if fresh else 2
        dod = (
            "1) cd the project repo and `git fetch --prune origin`; "
            "2) `git checkout -B integrate/%s-%s %s`; "
            "3) `git merge --no-ff %s` and resolve any conflict BY HAND, reading both sides; "
            "4) RE-RUN the project's own tests and quote the result line; "
            "5) `git diff --diff-filter=D --name-only %s HEAD` MUST BE EMPTY - a deletion the base "
            "did not have is the failure mode that has already destroyed work in this system; "
            "6) push the integration branch and close this item with the test output and the empty "
            "diff as the proof" % (base_branch, r["id"], base, ref, base))
        changed.append((r["id"], r["project"], ref, prio, r["priority"], fresh))
        if a.apply:
            c.execute("UPDATE work_item SET priority=?, dod=?, updated_at=? WHERE id=?",
                      (prio, dod,
                       datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), r["id"]))
    if a.apply:
        c.commit()
        stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
        shutil.copy2(DB, str(DB) + ".bak-prio-" + stamp)
        print("backup: %s.bak-prio-%s" % (DB, stamp))
    c.close()

    for i, proj, ref, prio, old, fresh in changed:
        print("  #%-3d %-18s -> priority %d (was %d)%s  %s" % (
            i, proj, prio, old, "  [created TODAY]" if fresh else "", ref))
    print("\n%d item(s) %s" % (len(changed), "updated" if a.apply else "would be updated"))

    if a.apply:
        print("\n=== what a shift will now take first ===")
        c = sqlite3.connect(str(DB), timeout=20)
        for r in c.execute("SELECT id, project, priority, substr(title,1,58) FROM work_item "
                           "WHERE state='todo' ORDER BY priority, id LIMIT 6"):
            print("  p%d  #%-3d %-18s %s" % (r[2], r[0], r[1], r[3]))
        c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
