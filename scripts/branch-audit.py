#!/usr/bin/env python3
"""Classify a git remote's branches by what would be lost if the ref were deleted.

Written 2026-09-15 against the shared journal hub (`/home/zabz/harness-config.git`), which had
accumulated **42 branches**, thirty of them `zabz-audit-20260914-rN` from a single day. Every one
exists because a session preserved work that had nowhere else to go -- the right instinct, and the
wrong long-term shape: the hub stopped being readable as a lineage, which is exactly what the fork
question (P134) needs it to be.

The rule this tool implements, and the reason it never deletes by pattern:

    a branch is REDUNDANT when its tip is an ancestor of another remote branch or of master --
    nothing becomes unreachable if the ref goes
    a branch is UNIQUE when nothing else reaches its tip -- it is somebody's preserved work

Only the caller can act on that. `--apply` deletes redundant branches, and it writes every deleted
branch's sha to a keep-file first, so even a mistake is one `git update-ref` away from undone.

Usage:
    python scripts/branch-audit.py [--remote origin] [--apply] [--keep-file PATH]
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone


def git(*args: str, cwd: str | None = None) -> str:
    out = subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError("git %s failed: %s" % (" ".join(args), (out.stderr or "").strip()[:200]))
    return out.stdout


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--remote", default="origin")
    ap.add_argument("--apply", action="store_true", help="delete the redundant branches")
    ap.add_argument("--keep-file", default=None, help="where to record deleted shas")
    args = ap.parse_args()

    remote = args.remote
    git("fetch", "--prune", remote, "+refs/heads/*:refs/remotes/%s/*" % remote)

    lines = [ln for ln in git("branch", "-r", "--format=%(refname:short)").splitlines() if ln.strip()]
    branches = [b for b in lines if b.startswith(remote + "/") and b != "%s/HEAD" % remote]
    master = "%s/master" % remote
    if master not in branches:
        print("REFUSE: no %s on this remote; refusing to guess which branch is the trunk" % master)
        return 2

    def is_ancestor(a: str, b: str) -> bool:
        out = subprocess.run(
            ["git", "merge-base", "--is-ancestor", a, b], capture_output=True, text=True
        )
        return out.returncode == 0

    unique, redundant, from_master = [], [], []
    for branch in branches:
        if branch == master:
            continue
        if is_ancestor(branch, master):
            from_master.append(branch)
            continue
        others = [b for b in branches if b not in (branch, master)]
        reachable_elsewhere = any(is_ancestor(branch, other) for other in others)
        (redundant if reachable_elsewhere else unique).append(branch)

    print("branches on %s: %d" % (remote, len(branches)))
    print("  reachable from master (free to delete): %d" % len(from_master))
    print("  reachable from another branch         : %d" % len(redundant))
    print("  UNIQUE -- somebody's only copy         : %d" % len(unique))
    print()
    print("unique branches (keep these):")
    for b in sorted(unique):
        sha = git("rev-parse", "--short", b).strip()
        when = git("log", "-1", "--format=%ci", b).strip()[:19]
        print("  %s  %s  %s" % (sha, when, b))

    to_delete = sorted(from_master + redundant)
    if not to_delete:
        print("\nnothing redundant.")
        return 0

    if not args.apply:
        print("\nredundant (would be deleted with --apply): %d" % len(to_delete))
        for b in to_delete[:40]:
            print("  %s" % b)
        return 0

    keep_file = args.keep_file or "/tmp/branch-audit-deleted-%s.txt" % datetime.now(
        timezone.utc
    ).strftime("%Y%m%d-%H%M%S")
    with open(keep_file, "w") as fh:
        for b in to_delete:
            fh.write("%s %s\n" % (git("rev-parse", b).strip(), b))
    print("\nrecorded %d shas in %s" % (len(to_delete), keep_file))
    deleted = 0
    for b in to_delete:
        ref = b[len(remote) + 1:]
        try:
            git("push", remote, "--delete", ref)
            deleted += 1
        except RuntimeError as exc:
            print("  could not delete %s: %s" % (b, exc))
    print("deleted %d of %d" % (deleted, len(to_delete)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
