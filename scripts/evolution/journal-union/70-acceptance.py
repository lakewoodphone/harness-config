#!/usr/bin/env python3
"""70-acceptance.py -- the acceptance test of the round-6 brief, restated so that every number
has a name, and run against the MERGED CANDIDATE tree plus the ORIGINAL five trees.

The brief's wording is: "the count of ids whose body differs FROM THE MERGED TREE must be 0".
That sentence has two possible readings and they do not agree, so both are computed here and
labelled:

  STRICT-DIFF   an id that appears in some source tree with a sha256 the merged tree does not
                hold AT THAT ID.  Because 364 ids genuinely carry more than one body, and one
                id can hold one body, this can never be 0 while colliding > 0.  It is the
                literal reading and it is reported with the ids so it can be audited.

  LOST          an id-and-body pair from a source tree whose BYTES are in no file of the merged
                tree at all.  This is what "nothing was lost" means and it must be 0.  A body
                that moved to a new id is not lost -- it is RELOCATED -- and is required to be
                reachable through the merged tree's own index/aliases.tsv, which repair-ids and
                dedupe write.

  INVENTED      a merged file whose bytes are in no source tree.  Must be 0.

Usage: 70-acceptance.py <merged-root> <manifests-dir> <merged-manifest-name> <tree> [<tree>...]
"""
from __future__ import annotations

import collections
import hashlib
import pathlib
import re
import sys

MARK = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|")


def load_manifest(p: pathlib.Path):
    out = []
    for ln in p.read_text(encoding="utf-8", errors="replace").splitlines():
        if not ln.strip():
            continue
        c = ln.split("\t")
        if len(c) >= 2:
            out.append((c[0], c[1]))
    return out


def main(argv):
    root = pathlib.Path(argv[1]).resolve()
    mdir = pathlib.Path(argv[2]).resolve()
    mman = argv[3]
    trees = argv[4:]

    # ---- the merged tree, read off the filesystem ----
    merged_at_id = collections.defaultdict(set)      # id -> {file sha}
    merged_sha_ids = collections.defaultdict(set)    # file sha -> {id}
    kind_of_id = {}
    n = 0
    for kinddir in sorted((root / "entries").iterdir()):
        if not kinddir.is_dir():
            continue
        for p in sorted(kinddir.glob("*.md")):
            raw = p.read_bytes()
            m = MARK.match(raw.decode("utf-8", "replace").split("\n")[0])
            if not m:
                print("NO MARKER %s" % p)
                continue
            i, sha = m.group("id"), hashlib.sha256(raw).hexdigest()
            merged_at_id[i].add(sha)
            merged_sha_ids[sha].add(i)
            kind_of_id[i] = m.group("kind")
            n += 1

    # ---- aliases the merged tree recorded ----
    aliases = collections.defaultdict(set)           # alias id -> {canonical ids}
    ap = root / "index" / "aliases.tsv"
    if ap.exists():
        for ln in ap.read_text(encoding="utf-8", errors="replace").splitlines()[1:]:
            if not ln.strip():
                continue
            c = ln.split("\t")
            if len(c) >= 3:
                aliases[c[0]].add(c[2])

    print("=" * 78)
    print("MERGED TREE  %s" % root)
    print("  entry files            %d" % n)
    print("  distinct ids           %d" % len(merged_at_id))
    print("  distinct file sha256   %d" % len(merged_sha_ids))
    print("  distinct (id,sha)      %d" % sum(len(v) for v in merged_at_id.values()))
    print("  alias rows             %d" % sum(len(v) for v in aliases.values()))
    print("")

    merged_shas = set(merged_sha_ids)
    strict_ids, lost, relocated, unaliased, invented = set(), [], [], [], []
    records = 0
    per_tree = {}
    for t in trees:
        mp = mdir / ("%s-manifest.tsv" % t)
        if not mp.exists():
            print("MISSING MANIFEST %s" % mp)
            continue
        rec = load_manifest(mp)
        per_tree[t] = len(rec)
        ex = rel = 0
        for i, sha in rec:
            records += 1
            if sha in merged_at_id.get(i, ()):
                ex += 1
                continue
            strict_ids.add(i)
            if sha in merged_shas:
                rel += 1
                relocated.append((t, i, sha, sorted(merged_sha_ids[sha])))
                if not (aliases.get(i, set()) & merged_sha_ids[sha]):
                    unaliased.append((t, i, sha, sorted(merged_sha_ids[sha])))
            else:
                lost.append((t, i, sha))
        per_tree[t] = (len(rec), ex, rel)
        print("  %-8s records=%-6d exact=%-6d relocated=%-5d lost=%d"
              % (t, len(rec), ex, rel, sum(1 for x in lost if x[0] == t)))
    print("")

    src_shas = set()
    for t in trees:
        mp = mdir / ("%s-manifest.tsv" % t)
        if mp.exists():
            src_shas |= {s for _i, s in load_manifest(mp)}
    invented = [s for s in merged_shas if s not in src_shas]

    print("=" * 78)
    print("ACCEPTANCE")
    print("  source (tree,id,sha) records           %d" % records)
    print("  STRICT-DIFF ids (literal reading)      %d" % len(strict_ids))
    print("  RELOCATED records (body kept, new id)  %d" % len(relocated))
    print("  relocated but NOT reachable by alias   %d" % len(unaliased))
    print("  LOST (id+body present nowhere)         %d" % len(lost))
    print("  INVENTED (merged body from no source)  %d" % len(invented))
    print("")
    if lost:
        print("  !! LOST -- the merge dropped these:")
        for t, i, s in lost[:40]:
            print("     %-8s %-10s %s" % (t, i, s))
    if unaliased:
        print("  !! RELOCATED WITHOUT AN ALIAS -- reachable by file, not by id:")
        for t, i, s, new in unaliased[:40]:
            print("     %-8s %-10s -> %s" % (t, i, new))
    if invented:
        print("  !! INVENTED:")
        for s in invented[:20]:
            print("     %s" % s)
    ok = not lost and not invented and not unaliased
    print("  VERDICT: %s" % ("PASS -- nothing lost, nothing invented, every relocated body "
                             "resolves through index/aliases.tsv" if ok else "FAIL"))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
