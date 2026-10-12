#!/usr/bin/env python3
"""Resolve the `git stash pop` conflict deterministically, losing no row.

Only two of the seven conflicted paths hold DATA. Both are append-only by construction,
so a union of rows is strictly more correct than either side and is the only resolution
that loses nothing:

  journal/alloc/bands.tsv    the id-reservation ledger (one row per reserved window)
  journal/state/status.tsv   the append-only status tier (one row per `resolve`)

The other five are generated caches -- journal/index/{entries.tsv,journal.db,stamp.json},
journal/state/absorb-stamp.json, journal/state/owner-questions.md -- which the journal
documents as rebuilding on demand. They take the published (post-rebase HEAD) version and
are then rebuilt by `journal.py index`.

Row order is preserved: every upstream row keeps its position, then rows only this
checkout had, in their original order.
"""
import subprocess
import sys
from pathlib import Path

repo = Path(r"C:\Users\ezabz\code\harness-config")
SNAP = Path(r"C:\Users\ezabz\harness-config-presync-backup-zabz-tech-20261011"
            r"\presync-tracked-20261011T2250Z")
APPEND_ONLY = ["journal/alloc/bands.tsv", "journal/state/status.tsv"]
CACHES = ["journal/index/entries.tsv", "journal/index/journal.db",
          "journal/index/stamp.json", "journal/state/absorb-stamp.json",
          "journal/state/owner-questions.md"]


def g(*a) -> bytes:
    return subprocess.run(["git"] + list(a), cwd=str(repo), capture_output=True).stdout


report = []
for rel in APPEND_ONLY:
    upstream = g("show", "HEAD:" + rel).decode("utf-8", "replace").splitlines()
    ours = (SNAP / rel).read_text(encoding="utf-8", errors="replace").splitlines()
    head, up_rows = upstream[0], [r for r in upstream[1:] if r.strip()]
    our_rows = [r for r in ours[1:] if r.strip()]
    seen, union = set(), []
    for r in up_rows + our_rows:
        if r not in seen:
            seen.add(r)
            union.append(r)
    only_up = [r for r in up_rows if r not in set(our_rows)]
    only_us = [r for r in our_rows if r not in set(up_rows)]
    out = "\n".join([head] + union) + "\n"
    (repo / rel).write_text(out, encoding="utf-8", newline="\n")
    # every row from both sides must be present
    assert all(r in out for r in up_rows), rel
    assert all(r in out for r in our_rows), rel
    report.append({"path": rel, "upstream_rows": len(up_rows), "our_rows": len(our_rows),
                   "union_rows": len(union), "only_upstream": len(only_up),
                   "only_ours": len(only_us),
                   "upstream_only_rows": only_up, "our_only_rows": only_us})
    print("%s: upstream=%d ours=%d union=%d (+%d upstream-only, +%d ours-only)"
          % (rel, len(up_rows), len(our_rows), len(union), len(only_up), len(only_us)))
    for r in only_up:
        print("   upstream only: %s" % r)
    for r in only_us:
        print("   ours only    : %s" % r)

for rel in CACHES:
    blob = g("show", "HEAD:" + rel)
    (repo / rel).write_bytes(blob)
    print("cache %s <- HEAD (%d B)" % (rel, len(blob)))

subprocess.run(["git", "add"] + APPEND_ONLY + CACHES, cwd=str(repo), check=True)
print("\nmarked resolved (git add) -- the stash is KEPT on the list, per the brief")
print("unmerged now:", g("diff", "--name-only", "--diff-filter=U").decode().strip() or "(none)")
