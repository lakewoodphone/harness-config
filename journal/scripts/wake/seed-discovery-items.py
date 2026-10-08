#!/usr/bin/env python3
"""A project with no repo and no items enters a deadlock. Break it by filing the discovery item.

THE DEADLOCK, measured 2026-09-28 19:43Z. Four of the nine projects the owner named have ZERO ledger
items: cfo, personality-system, rental-system, chumash. Three of them point at `/home/zabz/repos`,
which is a directory of repos and not a repository, and their registry notes say so plainly:

    rental-system       "REPO NOT YET ESTABLISHED - the first shift's job is to find the real codebase
                         and record its path in the ledger"
    chumash             "Repo not established (candidates exist on this machine); first shift finds it"
    personality-system  repo=/home/zabz/repos

And the shift contract tells a woken session to `claim-next` FROM THE LEDGER. With no item to claim it
gets `nothing-todo` and stops - so the discovery that would break the deadlock can never happen. The
project is scheduled, has a state file saying work remains, gets woken, and still does nothing.

THE FIX: for any enabled project that has NO ledger item at all AND whose repo is missing or is not a
git repository, file ONE discovery item with a definition of done that cannot be fudged:
  * find the real codebase (path, git remote, HEAD, and how it was identified);
  * if it genuinely cannot be found, file ONE owner-queue row asking for the path and say so;
  * `work.py project add` the discovered path into the registry so the next shift starts from it;
  * either way, leave at least one concrete item for that project in the ledger.

This runs from the ledger-keepalive source's neighbourhood rather than on a timer, but it is safe to
run repeatedly: an item is only filed when the project has NO items at all.

Usage: python3 seed-discovery-items.py [--apply]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

REG = Path("/home/zabz/bin/sources/projects.json")
WORK = "/home/zabz/bin/work.py"
PLACEHOLDER_REPOS = {"/home/zabz/repos", "/home/zabz/repos/", "", "."}


def ledger_items(project: str) -> int:
    p = subprocess.run(["python3", WORK, "list", "--project", project, "--json", "--limit", "200"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=90)
    if p.returncode != 0 or not (p.stdout or "").strip():
        return -1                      # unreadable, which is NOT the same as empty
    try:
        return len(json.loads(p.stdout))
    except Exception:
        return -1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    doc = json.loads(REG.read_text(encoding="utf-8"))
    filed = []
    for row in doc.get("projects", []):
        pid = row.get("id")
        if not row.get("enabled"):
            continue
        n = ledger_items(pid)
        if n != 0:
            continue                   # has items, or unreadable - never guess on unreadable
        repo = (row.get("repo") or "").strip()
        is_git = bool(repo) and (Path(repo) / ".git").exists()
        if is_git:
            continue                   # a real repo with no items is a different problem, handled elsewhere
        dod = (
            "1) FIND THE REAL CODEBASE for `%s`. Search this machine for it (a repo named after the "
            "project, a directory whose docs describe it, or the case/repo the OWNER named) and record: "
            "the absolute path, `git remote -v`, `git log --oneline -1`, and one sentence on HOW you "
            "identified it. "
            "2) REGISTER it: `python3 ~/bin/work.py project add --id %s --title '<title>' --repo "
            "<real-path>` - that writes the real path into the ledger's project row (the wake registry "
            "at ~/bin/sources/projects.json must ALSO be corrected to the real path, not "
            "/home/zabz/repos, by editing its `repo` field). "
            "3) IF IT TRULY CANNOT BE FOUND, do not guess and do not file invented work: add ONE row "
            "`python3 ~/bin/owner-queue.py add --question 'Where does the %s project live?' "
            "--recommendation '<your best candidate>' --options '<a>|<b>'` and say so. "
            "4) EITHER WAY, leave at least ONE concrete item in the ledger for this project with a "
            "definition of done that is a command. "
            "5) close this item with the path you found (or the queue row id) quoted."
            % (pid, pid, pid))
        why = (
            "the project has NO ledger items and its registry repo (%r) is not a git repository, so a "
            "woken shift gets `nothing-todo` and stops - the discovery that would break the deadlock can "
            "never happen. Owner named this project; the registry note says finding the codebase is the "
            "first shift's job." % repo)
        cmd = ["python3", WORK, "add", "--project", pid,
               "--title", "DISCOVERY: find the real codebase for %s and register its path" % pid,
               "--dod", dod, "--why", why, "--priority", "1", "--source", "seed-discovery"]
        if a.apply:
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", timeout=120)
            out = (p.stdout or "").strip()
            m = re.search(r'"id":\s*(\d+)', out)
            filed.append((pid, repo, m.group(1) if m else out[:60]))
        else:
            filed.append((pid, repo, "would-file"))
    for pid, repo, item in filed:
        print("  %-20s repo=%-22s -> item %s" % (pid, repo, item))
    print("\n%d discovery item(s) %s" % (len(filed), "filed" if a.apply else "to file"))
    if not filed:
        print("every project either has a real repo or already has ledger items")
    return 0


if __name__ == "__main__":
    sys.exit(main())
