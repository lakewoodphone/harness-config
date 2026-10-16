#!/usr/bin/env python3
"""fork-size.py — how many entry ids carry more than one body ACROSS trees, measured the same way twice.

WHY THIS AND NOT "check --cross-tree". `check --cross-tree` compares ONE tree against the others and
reports per-id differences; run against a tree that has just been repaired it counts the repair's own
renumbering (measured: 587 on the canonical tree against its pre-landing snapshots). That number is
not the fork. This one asks the source-against-source question directly -- for each (kind, id), how
many DISTINCT entries do the trees hold between them -- so two runs on two captures give a rate.

The identity is `journal.py`'s own `entry_hash`, which is what its intra-tree `check` uses to call two
files "one id, two different entries". Using the same function means this number and that error are
the same measurement.

Usage:
    python3 fork-size.py --trees /root/work/r8/trees
    python3 fork-size.py --trees /root/work/r8/trees --json
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import json
import pathlib
import sys

TOOL = pathlib.Path("/root/code/harness-config/journal/tools/journal.py")


def load_tool():
    spec = importlib.util.spec_from_file_location("_jm_fork", TOOL)
    m = importlib.util.module_from_spec(spec)
    m.JOURNAL = TOOL.parent.parent
    spec.loader.exec_module(m)
    return m


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--trees", required=True)
    ap.add_argument("--skip", default="",
                    help="comma-separated tree names to leave out. Needed for a RATE: the canonical "
                         "tree was REPAIRED between two captures, so including it compares a repaired "
                         "tree with an unrepaired one and reports the repair as growth")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--show", type=int, default=8)
    args = ap.parse_args()
    skip = {s.strip() for s in args.skip.split(",") if s.strip()}

    jm = load_tool()
    base = pathlib.Path(args.trees)
    if not base.is_dir():
        print(f"! {base} not found", file=sys.stderr)
        return 2

    by_id: dict = collections.defaultdict(dict)     # (kind,id) -> {hash: [trees]}
    per_tree = {}
    for t in sorted(x for x in base.iterdir() if x.is_dir()):
        if t.name in skip:
            continue
        ent = t / "entries"
        if not ent.is_dir():
            ent = t / "journal" / "entries"
        if not ent.is_dir():
            continue
        n = 0
        for f in ent.rglob("*.md"):
            if "/archive/" in str(f).replace("\\", "/"):
                continue
            e = jm.parse_entry(f, f.parent.name)
            if not e:
                continue
            n += 1
            h = jm.entry_hash(jm.effective_heading(e), e.get("body") or "")
            by_id[(e["kind"], e["id_full"])].setdefault(h, []).append(t.name)
        per_tree[t.name] = n

    total_ids = len(by_id)
    colliding = {k: v for k, v in by_id.items() if len(v) > 1}
    ids_seen_by_all = sum(1 for v in by_id.values() if len({x for lst in v.values() for x in lst}) == len(per_tree))
    extra_bodies = sum(len(v) - 1 for v in colliding.values())

    # which tree holds the body the fewest other trees hold -- the odd one out, who to go and ask
    minority = collections.Counter()
    for k, v in colliding.items():
        rarest = min(v.items(), key=lambda kv: len(kv[1]))
        minority[rarest[1][0]] += 1

    print(f"trees                : {len(per_tree)}")
    for t, n in sorted(per_tree.items()):
        print(f"   {t:18} {n:6} entries")
    print(f"ids seen             : {total_ids}")
    print(f"ids in every tree    : {ids_seen_by_all}")
    print(f"COLLIDING IDS        : {len(colliding)}        ({extra_bodies} surplus bodies)")
    print("collisions by kind   : " + " ".join(f"{k}:{v}" for k, v in
          sorted(collections.Counter(k[0] for k in colliding).items())))
    print("odd tree out         : " + " ".join(f"{t}:{n}" for t, n in minority.most_common()))
    print(f"\nfirst {args.show} colliding ids:")
    for k in sorted(colliding)[:args.show]:
        print("   %-10s %s" % (k[1], "  ".join(sorted(f"{t}" for lst in colliding[k].values() for t in lst))))

    if args.json:
        print(json.dumps({"trees": per_tree, "ids": total_ids, "colliding": len(colliding),
                          "surplus_bodies": extra_bodies}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
