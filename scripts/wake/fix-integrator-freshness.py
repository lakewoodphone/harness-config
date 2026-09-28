#!/usr/bin/env python3
"""work-integrator: never file an integration item from a stale library.

THE FLAW, found by measuring the clones the integrator reads (2026-09-28 19:30Z):
    kosher-filter-ai          HEAD e02538f  ahead 0, behind 19     <- 19 commits stale
    phone-and-tech-full       ahead 0, behind 0
    lpt-hub                   ahead 0, behind 0
    quickbooks-agent          ahead 3, behind 0
    personal-secretary-mvp    ahead 163, behind 176, 354 uncommitted files

So a "branch is not contained in the base" conclusion was drawn against a checkout that is 19 commits
behind - which is exactly how the rehearsal produced its scary number: `git diff --diff-filter=D` over
`origin/main..origin/agent/windows-broker-channel` reported 39 deleted files, and the reason is that
the branch was cut from a base that has since moved 48 commits. The deletions were the BASE's new
files, read as the branch's removals. That is the journal's standing lesson in a new costume: reading
the wrong data and believing it.

WHAT THIS ADDS
  * Each project's clone is FAST-FORWARDED to its upstream before any branch is judged, when the
    checkout is clean and strictly behind (never when diverged, never when dirty - a sync must not
    touch in-progress work).
  * If a clone is DIVERGED or DIRTY, the project is SKIPPED with the reason reported, because an
    integration item filed against a divergent checkout is a measurement of the cache, not of origin.
  * The report says, per project, what the clone's state was before judging branches.

Usage: python3 fix-integrator-freshness.py [--apply]  (patches /home/zabz/bin/work-integrator.py)
       python3 /home/zabz/bin/work-integrator.py --dry-run   (afterwards, to see the difference)
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

TARGET = Path("/home/zabz/bin/work-integrator.py")

SYNC_FN = '''

def sync_clone(repo: Path) -> tuple:
    """(state, detail) - make the checkout current before judging any branch.

    A stale clone makes "unmerged" a fact about the cache. Measured 2026-09-28: kosher-filter-ai was
    19 commits behind, and a diff across that gap reported 39 deleted files that were really the
    base's own additions.
    Returns state in: current | fast-forwarded | diverged | dirty | no-upstream | error
    """
    rc, out, err = git(repo, "status", "--porcelain")
    dirty = bool((out or "").strip())
    rc, counts, _ = git(repo, "rev-list", "--left-right", "--count", "HEAD...@{upstream}")
    if rc != 0 or not (counts or "").strip():
        return ("no-upstream" if dirty is False else "dirty"), "no upstream tracking branch"
    try:
        ahead, behind = (int(x) for x in counts.split()[:2])
    except Exception:
        return "error", "could not parse %r" % counts
    if ahead and behind:
        return "diverged", "ahead %d, behind %d - not touching a divergent checkout" % (ahead, behind)
    if ahead:
        return "current", "ahead %d (local commits, not behind)" % ahead
    if behind == 0:
        return "current", ("clean" if not dirty else "clean but %d uncommitted file(s)" % len(out.splitlines()))
    if dirty:
        return "dirty", "behind %d but %d file(s) uncommitted - not fast-forwarding over local work" % (
            behind, len(out.splitlines()))
    rc, out2, err2 = git(repo, "merge", "--ff-only", "@{upstream}", timeout=300)
    if rc != 0:
        return "error", "fast-forward failed: %s" % (err2 or out2)[:120]
    return "fast-forwarded", "was behind %d" % behind
'''

REPORT_INSERT = '''        state, detail = sync_clone(repo)
        if state in ("diverged", "dirty", "error"):
            report.append({"project": pid, "repo": real, "skipped": state,
                           "why": detail, "recent_unmerged": None, "filed": []})
            print("%-18s SKIPPED (%s): %s" % (pid, state, detail), file=sys.stderr)
            continue
'''


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    src = TARGET.read_text(encoding="utf-8")

    if "def sync_clone(" in src:
        print("already present")
    else:
        # insert the helper before main()
        marker = "\ndef main("
        if marker not in src:
            raise SystemExit("ERROR: no main() to anchor the helper")
        src = src.replace(marker, SYNC_FN + marker, 1)
        print("added sync_clone()")

    # call it right after the repo is resolved, before the fetch that judges branches
    anchor = '        base = pick_base(repo, row)\n'
    if REPORT_INSERT.strip() in src:
        print("skip block already present")
    else:
        if anchor not in src:
            raise SystemExit("ERROR: could not find the base selection to anchor the sync")
        src = src.replace(anchor, anchor + REPORT_INSERT, 1)
        print("added the stale/dirty skip")

    compile(src, str(TARGET), "exec")
    if not a.apply:
        print("dry run ok (use --apply)")
        return 0
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    shutil.copy2(TARGET, TARGET.with_name(TARGET.name + ".bak-freshness-" + stamp))
    TARGET.write_text(src, encoding="utf-8")
    print("patched %s" % TARGET)

    print("\n=== PROOF: run it and read what it says about each clone ===")
    r = subprocess.run([sys.executable, str(TARGET), "--dry-run"], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=600)
    out = (r.stdout or "") + (r.stderr or "")
    for line in out.splitlines():
        if "SKIPPED" in line or "recent_unmerged" in line or "integration item" in line:
            print("  " + line.strip())
    return 0


if __name__ == "__main__":
    sys.exit(main())
