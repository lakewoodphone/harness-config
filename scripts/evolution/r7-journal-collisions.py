#!/usr/bin/env python3
"""r7-journal-collisions.py — measure how far the journal has forked, before touching anything.

THE DEFECT. Round 6's `R6-JOURNAL` child found the journal living in five checkouts on five
machines, none a superset of another, with entry IDS reused for DIFFERENT BODIES. `journal.py
check` reports 0 errors in every tree, because it has no cross-tree rule. The journal is the only
memory an agent has between sessions, so this is the deepest continuity defect in the estate.

WHAT THIS DOES, AND WHAT IT REFUSES TO DO. It reads one `id<TAB>sha256` manifest per tree and
reports: the union, which ids are consistent, which COLLIDE, which are confined to a single tree,
and the kind mix. It writes `collisions.json` for the next step. **It writes nothing into any
journal and decides nothing about which body wins** — a colliding id is a decision to be made by
reading the two bodies, and this tool exists to say how many of those decisions there are so the
work can be sized honestly rather than guessed.

Usage:
    python r7-journal-collisions.py --dir ~/_r6            # analyse manifests in a directory
    python r7-journal-collisions.py --dir ~/_r6 --show 20  # print the first N collisions
"""
from __future__ import annotations

import argparse
import collections
import json
import pathlib
import sys

TREES = ("yoga", "cloud", "tech", "linux", "mac")


def load(base: pathlib.Path) -> dict[str, dict[str, str]]:
    trees: dict[str, dict[str, str]] = {}
    for name in TREES:
        p = base / f"manifest-{name}.tsv"
        if not p.is_file():
            print(f"  {name:6} MISSING  ({p.name})")
            continue
        d: dict[str, str] = {}
        for line in p.read_text(encoding="utf-8-sig").splitlines():
            parts = line.split("\t")
            if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
                d[parts[0].strip()] = parts[1].strip().lower()
        trees[name] = d
        print(f"  {name:6} {len(d):6} entries  from {p.name}")
    return trees


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory holding manifest-<tree>.tsv")
    ap.add_argument("--show", type=int, default=12, help="how many collisions to print")
    ap.add_argument("--json", dest="json_out", default=None, help="where to write collisions.json")
    args = ap.parse_args()
    base = pathlib.Path(args.dir).expanduser().resolve()

    print(f"trees present in {base}:")
    trees = load(base)
    if len(trees) < 2:
        print("! fewer than two trees -- nothing can be concluded about forking", file=sys.stderr)
        return 2

    ids: dict[str, dict[str, str]] = collections.defaultdict(dict)
    for t, d in trees.items():
        for k, v in d.items():
            ids[k][t] = v

    union = len(ids)
    consistent = sum(1 for v in ids.values() if len(set(v.values())) == 1)
    colliding = {k: v for k, v in ids.items() if len(set(v.values())) > 1}
    in_all = sum(1 for v in ids.values() if len(v) == len(trees))
    in_one = sum(1 for v in ids.values() if len(v) == 1)

    print()
    print(f"union ids              : {union}")
    print(f"same body everywhere   : {consistent}")
    print(f"COLLIDING bodies       : {len(colliding)}   <-- the work to be done")
    print(f"present in all {len(trees)} trees  : {in_all}")
    print(f"confined to ONE tree   : {in_one}")
    bykind = collections.Counter(k[0] for k in ids)
    print("by kind                : " + " ".join(f"{k}={v}" for k, v in sorted(bykind.items())))
    ckind = collections.Counter(k[0] for k in colliding)
    print("collisions by kind     : " + " ".join(f"{k}={v}" for k, v in sorted(ckind.items())))

    # How many trees does a colliding id appear in? 2 vs 3+ changes how much reading is needed.
    spread = collections.Counter(len(v) for v in colliding.values())
    print("collision spread       : " + " ".join(f"in-{k}-trees={v}" for k, v in sorted(spread.items())))

    print(f"\nfirst {args.show} collisions (id: tree=sha8):")
    for k in sorted(colliding)[:args.show]:
        print(f"  {k:8} " + "  ".join(f"{t}={h[:8]}" for t, h in sorted(colliding[k].items())))

    out = base / "collisions.json"
    if args.json_out:
        out = pathlib.Path(args.json_out).expanduser()
    out.write_text(json.dumps(colliding, indent=1), encoding="utf-8")
    print(f"\nwrote {out}  ({len(colliding)} colliding ids)")

    # ---- structure: is the fork a CONTIGUOUS BLOCK allocated differently, or scattered? --------
    # This decides the whole repair. A block means one machine minted a range of ids that another
    # machine had already used, and the fix is a bounded renumber on that machine. Scattered
    # collisions mean per-id adjudication, which is a different and much larger job.
    print("\n---- structure ----")
    minority: dict[str, int] = collections.Counter()
    unclassifiable: list[str] = []
    for k, v in colliding.items():
        by_sha: dict[str, list[str]] = collections.defaultdict(list)
        for t, h in v.items():
            by_sha[h].append(t)
        if len(by_sha) == 2 and len(v) >= 3:
            # exactly two bodies, and one tree holds the rarer one
            rare = min(by_sha.values(), key=len)
            if len(rare) == 1:
                minority[rare[0]] += 1
                continue
        unclassifiable.append(k)
    print("collisions where ONE tree is the odd one out: " +
          (" ".join(f"{t}={n}" for t, n in minority.most_common()) or "none"))
    print(f"collisions needing per-id reading (no single odd tree): {len(unclassifiable)}")

    # contiguous runs of ids by the numeric part, for the dominant minority tree
    if minority:
        top = minority.most_common(1)[0][0]
        owned = set()
        for k, v in colliding.items():
            by_sha: dict[str, list[str]] = collections.defaultdict(list)
            for t, h in v.items():
                by_sha[h].append(t)
            if len(by_sha) == 2:
                rare = min(by_sha.values(), key=len)
                if len(rare) == 1 and rare[0] == top:
                    owned.add(k)

        def num(k: str) -> int:
            try:
                return int("".join(c for c in k if c.isdigit()))
            except ValueError:
                return -1

        ordered = sorted(owned, key=num)
        runs: list[list[str]] = []
        for k in ordered:
            if runs and num(k) - num(runs[-1][-1]) <= 2:
                runs[-1].append(k)
            else:
                runs.append([k])
        print(f"\n{top}: {len(owned)} ids in {len(runs)} contiguous run(s):")
        for r in runs:
            print(f"  {r[0]}..{r[-1]}  ({len(r)} ids)")

    # ---- the merge plan: which tree should be the base, and how many files must cross ----------
    # journal.py ALREADY OWNS the intra-tree repair (`dedupe` for exact-content duplicates,
    # `repair-ids` for an id colliding with different content, `pairs` to list them). What nothing
    # owns is the CROSS-tree union, because journal.py has never seen more than one tree. So the
    # plan is: union into one tree first, then let journal.py's own commands repair it.
    print("\n---- merge plan ----")
    extra_bodies = sum(max(1, len(set(v.values()))) for v in ids.values())
    print(f"distinct entry BODIES in the union : {extra_bodies}  (union ids {union} + "
          f"{extra_bodies - union} colliding second/third bodies)")
    coverage = {}
    for t in trees:
        have = {k: h for k, h in ids.items() if t in h}
        coverage[t] = have
    best = max(trees, key=lambda t: len(coverage[t]))
    print(f"tree with the widest coverage      : {best} ({len(coverage[best])} of {union} ids)")
    for t in sorted(trees):
        have = coverage[t]
        missing_vs_union = union - len(have)
        unique_to_t = sum(1 for k, v in ids.items() if list(v) == [t])
        print(f"  {t:6} has {len(have):5}  missing {missing_vs_union:5}  unique-to-it {unique_to_t:4}")
    # files that must move from tree t into the base, counted as (id, body) pairs not already there
    base_pairs = {(k, v[best]) for k, v in ids.items() if best in v}
    move = 0
    for t in trees:
        if t == best:
            continue
        for k, h in coverage[t].items():
            if (k, h) not in base_pairs:
                move += 1
    print(f"entry files that must cross into {best}: {move}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
