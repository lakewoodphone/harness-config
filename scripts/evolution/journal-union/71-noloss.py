#!/usr/bin/env python3
"""71-noloss.py -- the cross-tree no-loss gate, run with journal.py's OWN parser and the SAME
presence buckets `tools/verify.py` uses.

`tools/verify.py` answers "did every legacy entry survive the rebuild?" for ONE tree, comparing
`log/**` + the flat files against `entries/`. It cannot be pointed at five trees, and it takes its
idea of "the same entry" from the FROZEN v1 parser while reading the new tree by hand. This script
does the cross-tree version of the same test, but parses BOTH sides with the tree's own
`journal.py` (`load_entries()`), so a difference in parser cannot masquerade as a lost entry.

Presence, exactly as verify.py defines it (a copy is NOT lost when it is the same LOGICAL entry):
    exact                    same kind + same heading + same body
    same_entry_other_id      same kind + same normalised body (or title, for heading-only entries)
    aliased                  the source id is in the merged tree's index/aliases.tsv
    id_present_but_text_differs   the id is live in the merged tree with different text (a WARN)
    MISSING                  none of the above -- a lost entry

A raw file-sha256 comparison is the WRONG instrument here and is deliberately not used:
`repair-ids` rewrites the marker id and the heading's id token on the copies it renumbers, so
every renumbered entry has new bytes while holding the same entry; `dedupe` MOVES surplus copies
into archive/ so their bytes leave entries/. Both are accounted for, neither is a loss.
"""
from __future__ import annotations

import collections
import importlib.util
import pathlib
import sys

R7 = pathlib.Path("/root/work/r7")
MERGED = R7 / "merged-journal"
TREES = ["yoga", "cloud", "tech", "linux", "mac"]


def load_module(root: pathlib.Path):
    spec = importlib.util.spec_from_file_location("jm", root / "tools" / "journal.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    jm = load_module(MERGED)
    jm.JOURNAL = MERGED
    live, problems = jm.load_entries()
    print("merged root            %s" % MERGED)
    print("merged entries parsed  %d   problems %d" % (len(live), len(problems)))

    by_hash = collections.defaultdict(list)
    by_ident = collections.defaultdict(list)
    for e in live:
        by_hash[(e["kind"], jm.entry_hash(e["heading"], e["body"]))].append(e)
        by_ident[(e["kind"], jm.identity_of(e["kind"], e["heading"], e["body"]))].append(e)
    live_ids = {e["id_full"] for e in live}

    aliases = {}
    ap = MERGED / "index" / "aliases.tsv"
    if ap.exists():
        for ln in ap.read_text(encoding="utf-8", errors="replace").split("\n")[1:]:
            if not ln.strip():
                continue
            c = ln.split("\t")
            if len(c) >= 3:
                aliases[c[0]] = c[2]
    print("merged alias rows      %d" % len(aliases))
    print("")
    print("%-7s %7s %7s %11s %8s %14s %8s" %
          ("tree", "entries", "exact", "same_body", "aliased", "id_text_diff", "MISSING"))

    all_missing = []
    merged_idents = set(by_ident)
    total = collections.Counter()
    for t in TREES:
        # parse the SOURCE tree with the SAME parser
        jm.JOURNAL = TREES_ROOT / t / "journal"
        jm._ENTRIES_CACHE.clear()
        src, _p = jm.load_entries()
        buckets = collections.Counter()
        missing = []
        for e in src:
            k_h = (e["kind"], jm.entry_hash(e["heading"], e["body"]))
            if by_hash.get(k_h):
                buckets["exact"] += 1
                continue
            k_i = (e["kind"], jm.identity_of(e["kind"], e["heading"], e["body"]))
            if by_ident.get(k_i):
                buckets["same_entry_other_id"] += 1
                continue
            if e["id_full"] and e["id_full"] in aliases:
                buckets["aliased"] += 1
                continue
            if e["id_full"] in live_ids:
                buckets["id_present_but_text_differs"] += 1
                continue
            buckets["MISSING"] += 1
            missing.append((t, e["id_full"], (e["heading"] or "")[:60], e["file"]))
        print("%-7s %7d %7d %11d %8d %14d %8d"
              % (t, len(src), buckets["exact"], buckets["same_entry_other_id"],
                 buckets["aliased"], buckets["id_present_but_text_differs"], buckets["MISSING"]))
        all_missing += missing
        total += buckets
    jm.JOURNAL = MERGED
    jm._ENTRIES_CACHE.clear()
    live2, _ = jm.load_entries()

    # the other direction: does the merged tree hold an entry no source tree had?
    src_idents = set()
    for t in TREES:
        jm.JOURNAL = TREES_ROOT / t / "journal"
        jm._ENTRIES_CACHE.clear()
        s, _p = jm.load_entries()
        for e in s:
            src_idents.add((e["kind"], jm.identity_of(e["kind"], e["heading"], e["body"])))
    jm.JOURNAL = MERGED
    jm._ENTRIES_CACHE.clear()
    invented = [e for e in live2
                if (e["kind"], jm.identity_of(e["kind"], e["heading"], e["body"])) not in src_idents]

    print("")
    print("TOTAL   %7d %7d %11d %8d %14d %8d"
          % (sum(1 for _ in []) + total["exact"] + total["same_entry_other_id"]
             + total["aliased"] + total["id_present_but_text_differs"] + total["MISSING"],
             total["exact"], total["same_entry_other_id"], total["aliased"],
             total["id_present_but_text_differs"], total["MISSING"]))
    print("INVENTED in the merged tree (identity in no source tree) : %d" % len(invented))
    for e in invented[:20]:
        print("   %-10s %s" % (e["id_full"], e["file"]))
    if all_missing:
        print("")
        print("!! MISSING -- a source entry's logical identity is nowhere in the merged tree:")
        for t, i, h, f in all_missing[:40]:
            print("   %-7s %-10s %-12s %s" % (t, i, f, h))
    ok = not all_missing and not invented
    print("")
    print("VERDICT: %s" % ("PASS -- every entry of every tree is present in the merged tree by "
                           "identity, and the merged tree invents nothing" if ok else "FAIL"))
    return 0 if ok else 1


TREES_ROOT = R7 / "trees"

if __name__ == "__main__":
    raise SystemExit(main())
