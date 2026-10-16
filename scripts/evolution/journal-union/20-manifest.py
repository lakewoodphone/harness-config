#!/usr/bin/env python3
"""20-manifest.py -- regenerate a per-tree `id<TAB>sha256` manifest from an extracted tree.

Same semantics as the manifests the manager published (sha256 of the file bytes, id as
the entry's identity) but read from the tree that is actually on disk NOW, and with the
id taken from the FIRST-LINE marker `<!-- e:<kind>|<id>|... -->` rather than the file
stem, so a tree that already violates `stem == marker` is visible instead of hidden.

Reports, per tree: files, unique marker ids, ids carried by more than one file, files
whose stem differs from the marker id, and first lines that are not a marker at all.
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import sys

MARKER = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|")
KINDS = ("decisions", "handoff", "lessons", "pain", "wins")


def main(argv):
    tree = pathlib.Path(argv[1]).resolve()
    out = pathlib.Path(argv[2])
    ent = tree / "entries"
    rows = []
    dup = {}
    stem_mismatch = []
    malformed = []
    for kind in KINDS:
        d = ent / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            raw = p.read_bytes()
            sha = hashlib.sha256(raw).hexdigest()
            first = raw.decode("utf-8", "replace").split("\n")[0]
            m = MARKER.match(first)
            if not m:
                malformed.append(str(p.relative_to(tree)))
                continue
            i = m.group("id")
            if i != p.stem:
                stem_mismatch.append("%s marker=%s" % (p.name, i))
            dup[i] = dup.get(i, 0) + 1
            rows.append((i, sha))
    rows.sort()
    out.write_text("".join("%s\t%s\n" % r for r in rows), encoding="utf-8")
    multi = sorted(k for k, v in dup.items() if v > 1)
    print("tree=%-8s files=%d manifest_lines=%d unique_ids=%d ids_multi_file=%d "
          "stem!=marker=%d malformed=%d -> %s"
          % (tree.name, len(rows), len(rows), len(dup), len(multi),
             len(stem_mismatch), len(malformed), out))
    for x in stem_mismatch[:10]:
        print("   STEM  %s" % x)
    for x in malformed[:10]:
        print("   BAD   %s" % x)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
