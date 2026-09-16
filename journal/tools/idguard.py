#!/usr/bin/env python3
"""idguard -- collision-safe id allocation for the sharded journal.

WHY THIS EXISTS
---------------
On 2026-09-15 two machines minted the same journal entry ids for different entries: 98
collisions, found only when a merge refused to resolve, at the cost of a session. Three
things were true and all three are fixed or reported here:

1. `journal.py next-id` computes its floor from `max_number` (the working index) and
   `git_max`, whose own docstring claims "Highest number visible in any local or remote git
   ref" and which does `git fetch --all` first -- but then greps only the WORKING TREE and
   HEAD. Ids that arrived by fetch and were never merged are invisible to it, which is
   exactly the window in which two machines mint the same number. `mint_floor()` below reads
   every ref, so the floor is above anything any ref has ever used.
2. `journal.py check` compares ids within the working tree only, so it reported 0 errors on
   two machines that collided with each other. `collisions()` below reports that.
3. Nothing distinguished a real collision (two different entries wearing one id, to be
   renumbered) from a divergence (one entry edited on both sides, to be merged). The rule is
   host/date/heading, NOT the content hash: a hash-only test flags every ordinary edit.

USAGE
    python journal/tools/idguard.py                 # this tree vs its upstream
    python journal/tools/idguard.py --strict        # exit 1 on any collision
    python journal/tools/idguard.py --refs A,B      # explicit refs
    python journal/tools/idguard.py --local-rev A --refs B   # two refs, for testing
    python journal/tools/idguard.py --floor         # next free id per kind

Read-only. It never writes to the journal, and it never resolves anything: renumbering an
entry is a deliberate act by whoever owns the history (see the 2026-09-15 convergence in
decisions D191/D193).
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys

KIND_LETTERS = {"handoff": "H", "lessons": "L", "pain": "P", "decisions": "D", "wins": "W"}
INDEX_RELPATH = os.path.join("journal", "index", "entries.tsv")

# index/entries.tsv columns (header): kind id_full num suffix date host status heading file
# line_start line_end hash  -- so host is 5, date is 4, heading is 7, hash is 11.
COL_DATE, COL_HOST, COL_HEAD, COL_HASH = 4, 5, 7, 11


def _repo_root(start: str) -> str:
    """The git repo holding the journal: this file lives at <repo>/journal/tools/."""
    return os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(start))))


def _git(repo: str, *args: str, timeout: int = 30):
    try:
        p = subprocess.run(["git", "-C", repo] + list(args), capture_output=True, text=True,
                           timeout=timeout)
    except Exception:
        return None
    return p.stdout if p.returncode == 0 else None


def upstream_ref(repo: str):
    out = _git(repo, "rev-parse", "--abbrev-ref", "@{upstream}")
    return (out or "").strip() or None


def all_refs(repo: str) -> list:
    out = _git(repo, "for-each-ref", "--format=%(refname)", "refs/heads", "refs/remotes")
    if not out:
        return []
    head = (_git(repo, "rev-parse", "--abbrev-ref", "HEAD") or "").strip()
    return [r for r in out.split()
            if r != "refs/heads/" + head and not r.endswith("/HEAD")]


def rows_from_text(text: str) -> dict:
    """id_full -> {date, host, heading, hash}."""
    rows = {}
    if not text:
        return rows
    for line in text.splitlines()[1:]:
        parts = line.split("\t")
        if len(parts) > COL_HASH and parts[1]:
            rows[parts[1]] = {"date": parts[COL_DATE], "host": parts[COL_HOST],
                              "heading": parts[COL_HEAD], "hash": parts[COL_HASH]}
    return rows


def index_at(repo: str, rev: str):
    """The index as committed at `rev`: one blob read, no tree walk."""
    return rows_from_text(_git(repo, "show", "%s:%s" % (rev, INDEX_RELPATH.replace(os.sep, "/"))))


def index_on_disk(repo: str) -> dict:
    path = os.path.join(repo, INDEX_RELPATH)
    return rows_from_text(open(path, encoding="utf-8").read()) if os.path.exists(path) else {}


def collisions(repo: str, local=None, refs=None):
    """(collisions, divergences) between `local` and each ref.

    collision  : same id, different host OR date OR heading -> two different entries wearing
                 one id. Renumber one of them.
    divergence : same id, same host/date/heading, content differs -> one entry edited on both
                 sides. Merge it; do NOT renumber.
    """
    local = index_on_disk(repo) if local is None else local
    refs = ([upstream_ref(repo)] if refs is None else refs)
    coll, div = [], []
    for ref in [r for r in refs if r]:
        rows = index_at(repo, ref)
        for id_full, theirs in rows.items():
            mine = local.get(id_full)
            if not mine or mine["hash"] == theirs["hash"]:
                continue
            if (mine["host"] != theirs["host"] or mine["date"] != theirs["date"]
                    or mine["heading"] != theirs["heading"]):
                coll.append({"id": id_full, "ref": ref, "mine": mine, "theirs": theirs})
            else:
                div.append({"id": id_full, "ref": ref, "mine": mine, "theirs": theirs})
    return coll, div


def mint_floor(repo: str, refs=None):
    """Next free number per kind, above the working index AND every ref. Safest to over-allot."""
    tops = {k: 0 for k in KIND_LETTERS}
    sources = [index_on_disk(repo)] + [index_at(repo, r) for r in (refs if refs is not None
                                                                  else all_refs(repo))]
    for rows in sources:
        for id_full in rows:
            for kind, letter in KIND_LETTERS.items():
                if id_full.startswith(letter):
                    tail = id_full[len(letter):]
                    if tail.isdigit():
                        tops[kind] = max(tops[kind], int(tail))
    return {k: "%s%d" % (KIND_LETTERS[k], tops[k] + 1) for k in KIND_LETTERS}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=None, help="repo holding the journal (default: inferred)")
    ap.add_argument("--refs", default=None, help="comma-separated refs (default: the upstream)")
    ap.add_argument("--local-rev", default=None, help="compare two refs instead of the tree")
    ap.add_argument("--floor", action="store_true", help="print the next free id per kind")
    ap.add_argument("--strict", action="store_true", help="exit 1 if any collision exists")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)

    repo = a.repo or _repo_root(__file__)
    refs = a.refs.split(",") if a.refs else None

    if a.floor:
        floor = mint_floor(repo, refs)
        print(json.dumps(floor, indent=1, sort_keys=True) if a.json
              else "next free: " + ", ".join("%s=%s" % (k, v) for k, v in sorted(floor.items())))
        return 0

    local = index_at(repo, a.local_rev) if a.local_rev else None
    coll, div = collisions(repo, local=local, refs=refs)
    if a.json:
        print(json.dumps({"collisions": coll, "divergences": div}, indent=1))
    else:
        for c in coll[:20]:
            print("COLLISION  %s on %s: host %s vs %s, heading %r vs %r"
                  % (c["id"], c["ref"], c["mine"]["host"], c["theirs"]["host"],
                     c["mine"]["heading"][:40], c["theirs"]["heading"][:40]))
        for d in div[:20]:
            print("divergence %s on %s: same host/date/heading, content differs -- merge, do not "
                  "renumber" % (d["id"], d["ref"]))
        print("collisions: %d   divergences: %d" % (len(coll), len(div)))
    if a.strict and coll:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
