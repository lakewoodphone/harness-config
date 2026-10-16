#!/usr/bin/env python3
"""r7-journal-source-census.py — find every journal tree on a machine, and say which of them
holds a BODY that the machine's own main checkout does not.

WHY THIS EXISTS. Rounds 5-6 treated the journal fork as "five trees, one per machine". Measured
2026-10-16 on `secratary-cloud`, that is not the whole set: the authority alone carries 21
directories containing `journal/entries`, and `/root/work/wt-item221` — the worktree of a branch
that was never merged — holds **234 entry ids the authority's own checkout does not have**
(`git cat-file -e HEAD:journal/entries/decisions/D3111.md` -> absent in main, present in the
worktree). A union built from five trees that were chosen by machine name cannot see that, and
"0 bodies missing" over the wrong source set is a green light to lose 234 entries.

The instrument is deliberately the SAME body signature `r7-verify-body-loss.py` uses — header and
`<!-- j2 -->` metadata stripped, every id-shaped token normalised, whitespace collapsed, `archive/`
excluded — so a census finding and a merge acceptance test cannot disagree about what "a body" is.

WHAT IT DOES NOT DO. It reads only. It moves nothing, writes nothing into any journal, and decides
nothing about which body wins a collision. It exists to size the job honestly: how many trees are
there really, and how much content is confined to one of them.

Usage:
    python3 r7-journal-source-census.py --scan /root --ref /root/code/harness-config/journal
    python3 r7-journal-source-census.py --scan C:/Users/ezabz/code --ref .../harness-config/journal \
        --out census-yoga.tsv
"""
from __future__ import annotations

import argparse
import collections
import importlib.util
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
KINDS = ("decisions", "handoff", "lessons", "pain", "wins")


def _load_sig():
    """Import body_sig from its own file so the two instruments cannot drift apart."""
    p = HERE / "r7-verify-body-loss.py"
    spec = importlib.util.spec_from_file_location("r7vbl", p)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m.body_sig


# Directories that never contain a journal tree but cost minutes to walk. `.git` is the important
# one: every clone and worktree has a full object store under it, and a plain rglob over 28 repos
# spends nearly all its time there. This pruning is what makes the census take seconds, not hours.
PRUNE = {"node_modules", ".git", ".venv", "venv", "__pycache__", "dist", "build", ".next",
         "target", "vendor", "site-packages", ".cache", ".tox", ".mypy_cache", ".pytest_cache",
         "obj", "bin", ".gradle", ".terraform", "coverage", ".parcel-cache"}


def find_trees(root: pathlib.Path, maxdepth: int) -> list[pathlib.Path]:
    """Every directory that CONTAINS a journal/entries, i.e. every journal root under `root`."""
    import os

    out: list[pathlib.Path] = []
    root = root.resolve()
    for dirpath, dirnames, _files in os.walk(root):
        d = pathlib.Path(dirpath)
        try:
            depth = len(d.relative_to(root).parts)
        except ValueError:
            depth = 0
        if depth >= maxdepth:
            dirnames[:] = []
            continue
        dirnames[:] = [n for n in dirnames if n not in PRUNE]
        if d.name == "entries" and d.parent.name == "journal":
            out.append(d.parent)
            dirnames[:] = []
    return sorted(set(out))


def collect(entries_dir: pathlib.Path, body_sig) -> dict[str, str]:
    """id -> body signature for every live entry. archive/ is skipped (retired copies)."""
    got: dict[str, str] = {}
    for f in entries_dir.rglob("*.md"):
        if "/archive/" in str(f).replace("\\", "/"):
            continue
        got[f.stem] = body_sig(f, True)
    return got


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--scan", required=True, help="root to search for journal trees")
    ap.add_argument("--ref", required=True, help="the reference journal root (main checkout)")
    ap.add_argument("--maxdepth", type=int, default=6)
    ap.add_argument("--out", default=None, help="write the per-tree TSV here")
    ap.add_argument("--show", type=int, default=8, help="example ids per risky tree")
    args = ap.parse_args()

    body_sig = _load_sig()
    ref = pathlib.Path(args.ref)
    if not (ref / "entries").is_dir():
        print(f"! reference {ref}/entries not found", file=sys.stderr)
        return 2

    print(f"reference : {ref}")
    ref_ids = collect(ref / "entries", body_sig)
    ref_bodies = set(ref_ids.values())
    print(f"reference : {len(ref_ids)} live entries, {len(ref_bodies)} distinct bodies\n")

    trees = find_trees(pathlib.Path(args.scan), args.maxdepth)
    print(f"journal trees found under {args.scan}: {len(trees)}\n")

    header = ("tree", "files", "ids", "ids_not_in_ref", "bodies_not_in_ref", "example_ids")
    rows = []
    risky_total_bodies = 0
    print("%-58s %6s %6s %14s %16s" % header[:5])
    for t in trees:
        got = collect(t / "entries", body_sig)
        if not got:
            continue
        new_ids = sorted(set(got) - set(ref_ids))
        new_bodies = sorted({s for i, s in got.items() if s not in ref_bodies})
        # an id absent from the reference whose BODY is also absent is real content nobody else has
        real = sorted(i for i in new_ids if got[i] not in ref_bodies)
        if t == ref:
            new_ids, new_bodies, real = [], [], []
        risky_total_bodies += len(real)
        if new_ids or new_bodies:
            print("%-58s %6d %6d %14d %16d"
                  % (str(t)[-58:], len(got), len(got), len(new_ids), len(real)))
            if real and args.show:
                print("      e.g. " + " ".join(real[:args.show]))
        rows.append((str(t), len(got), len(new_ids), len(real)))

    print(f"\nTOTAL live entries confined to ONE tree and absent from the reference: {risky_total_bodies}")
    if args.out:
        p = pathlib.Path(args.out)
        with p.open("w", encoding="utf-8", newline="\n") as fh:
            fh.write("tree\tfiles\tids_not_in_ref\tbodies_not_in_ref\n")
            for r in rows:
                fh.write("%s\t%d\t%d\t%d\n" % r)
        print(f"wrote {p}  ({len(rows)} trees)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
