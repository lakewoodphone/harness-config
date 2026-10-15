#!/usr/bin/env python3
"""r7-verify-merge.py — the acceptance test for a journal union: NOTHING WAS LOST.

WHY THIS EXISTS AND WHY IT IS NOT "residual collisions == 0". The round-6 brief for the merge said
the acceptance test was "the count of ids whose body differs from the merged tree must be 0". That is
**structurally impossible and was the wrong test**: an id holds exactly one body, so after a union the
losers are renamed to fresh ids and the count of ids that USED to carry more than one body stays what
it always was. The builder correctly refused to report 0 and said so.

The test that answers the real question is a set comparison on CONTENT, not on ids:

    every distinct body present in any source tree must be present in the merged tree

Because bodies are content-addressed here by sha256, that is exact: no body lost, nothing invented.
Where an id maps to several bodies, that is expected and is not a failure -- it is the reason the
union exists. Aliasing is reported separately so a reader can see the difference.

Usage:
    python r7-verify-merge.py --dir ~/_r6 --merged merged.tsv
"""
from __future__ import annotations

import argparse
import collections
import pathlib
import sys

SOURCES = ("yoga", "cloud", "tech", "linux", "mac")


def load(p: pathlib.Path) -> dict[str, set[str]]:
    """sha256 -> the set of ids it is filed under (or, for a source, the trees it came from)."""
    out: dict[str, set[str]] = collections.defaultdict(set)
    for line in p.read_text(encoding="utf-8-sig").splitlines():
        parts = line.split("\t")
        if len(parts) >= 2 and parts[0].strip() and parts[1].strip():
            out[parts[1].strip().lower()].add(parts[0].strip())
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True, help="directory holding manifest-<tree>.tsv")
    ap.add_argument("--merged", default="merged.tsv", help="manifest of the merged tree")
    args = ap.parse_args()
    base = pathlib.Path(args.dir).expanduser().resolve()

    src: dict[str, set[str]] = collections.defaultdict(set)
    per_tree: dict[str, int] = {}
    for name in SOURCES:
        p = base / f"manifest-{name}.tsv"
        if not p.is_file():
            print(f"  {name:6} MISSING")
            continue
        d = load(p)
        per_tree[name] = len(d)
        for h, ids in d.items():
            src[h] |= {f"{name}:{i}" for i in ids}
        print(f"  {name:6} {len(d):6} distinct bodies")

    mp = base / args.merged
    if not mp.is_file():
        print(f"! {mp} not found", file=sys.stderr)
        return 2
    merged = load(mp)

    missing = sorted(set(src) - set(merged))
    extra = sorted(set(merged) - set(src))
    shared = len(set(src) & set(merged))

    print(f"\nsource trees             : {len(per_tree)}")
    print(f"distinct bodies, sources : {len(src)}")
    print(f"bodies in the merged tree: {len(merged)}")
    print(f"present in both          : {shared}")
    print(f"**MISSING from merged**  : {len(missing)}")
    print(f"**INVENTED in merged**   : {len(extra)}")
    multi = sum(1 for ids in merged.values() if len(ids) > 1)
    print(f"bodies filed under >1 id : {multi}  (expected: an id holds one body, so a merged body "
          f"under a new id is normal)")

    if missing:
        print("\nthe bodies that were LOST, and where they came from:")
        for h in missing[:20]:
            print(f"  {h[:16]}  from {sorted(src[h])}")
    if extra:
        print("\nbodies the merged tree has that no source did:")
        for h in extra[:10]:
            print(f"  {h[:16]}  as {sorted(merged[h])}")

    ok = not missing and not extra
    print(f"\nVERDICT: {'NO BODY LOST' if not missing else f'{len(missing)} BODY/BODIES LOST'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
