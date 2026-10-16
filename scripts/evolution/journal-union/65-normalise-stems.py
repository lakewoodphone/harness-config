#!/usr/bin/env python3
"""65-normalise-stems.py -- make the file NAME of every entry equal to the id in its marker.

WHY THIS STEP EXISTS -- it is not in the brief, and it is required.

The brief's plan produces second-copy files named `<id>b.md`, `<id>c.md` ... whose marker still
carries the ORIGINAL id. `journal.py repair-ids` then renumbers the surplus copies of each id,
keeping the EARLIEST by (date, file). It does not care which FILE NAME the survivor has, so
whenever the earliest copy is one of the suffixed ones, the survivor of id X is left sitting in
`<X>b.md` -- and `journal.py check` reports, for every such file,

    ERROR entries/<kind>/<X>b.md: id in the file name (<X>b) disagrees with the marker (X)

MEASURED on this tree: 94 of them after `dedupe --apply` + `repair-ids --apply`, so `check`
still exited 1. `repair-ids` fixed the ID collision and left the NAME wrong.

This script performs a pure RENAME -- no byte of any entry changes -- of each such file onto its
own id. It refuses, loudly, if any id is carried by more than one file (that would mean the
repair did not finish), and it refuses per file if the target name is already taken. Renames go
through a temporary name that does not end in `.md`, so no reader can ever see a half-done state
and no entry can be parsed as the wrong id mid-run.
"""
from __future__ import annotations

import re
import pathlib
import sys

MARK = re.compile(r"^<!--\s*e:(?P<kind>[a-z]+)\|(?P<id>[^|]*)\|")
KINDS = ("decisions", "handoff", "lessons", "pain", "wins")


def main(argv):
    root = pathlib.Path(argv[1] if len(argv) > 1 else "/root/work/r7/merged-journal").resolve()
    apply_ = "--apply" in argv
    by_id = {}
    files = []
    for kind in KINDS:
        d = root / "entries" / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            m = MARK.match(p.read_bytes().decode("utf-8", "replace").split("\n")[0])
            if not m:
                print("NO MARKER %s" % p)
                return 2
            files.append((p, m.group("id")))
            by_id.setdefault(m.group("id"), []).append(p)

    multi = {i: v for i, v in by_id.items() if len(v) > 1}
    print("root=%s" % root)
    print("entry files=%d  distinct ids=%d  ids carried by >1 file=%d"
          % (len(files), len(by_id), len(multi)))
    for i, v in list(multi.items())[:10]:
        print("   MULTI %s -> %s" % (i, [str(p) for p in v]))
    if multi:
        print("REFUSING: the id repair has not finished; normalising names now would be a guess.")
        return 2

    plan, blocked = [], []
    for p, i in files:
        if p.stem == i:
            continue
        target = p.with_name(i + ".md")
        if target.exists():
            blocked.append((str(p), str(target)))
            continue
        plan.append((p, target))

    print("files whose stem != marker id : %d" % (len(files) - sum(1 for p, i in files if p.stem == i)))
    print("renames planned               : %d" % len(plan))
    print("target name already taken     : %d" % len(blocked))
    for a, b in blocked[:10]:
        print("   BLOCKED %s -> %s" % (a, b))
    if blocked:
        print("REFUSING: %d target name(s) are occupied; nothing renamed." % len(blocked))
        return 2
    if not apply_:
        for p, t in plan[:15]:
            print("   would rename %s -> %s" % (p.relative_to(root), t.name))
        print("   ... and %d more" % max(0, len(plan) - 15))
        print("DRY RUN -- re-run with --apply")
        return 0

    tmp = []
    for p, t in plan:
        # a temporary name that does NOT end in .md, so no reader can parse it as an entry
        q = p.with_name(p.stem + ".__r7renaming")
        p.rename(q)
        tmp.append((q, t))
    for q, t in tmp:
        q.rename(t)
    print("renamed %d file(s); 0 bytes changed, 0 files deleted" % len(plan))

    # verify it took
    bad = 0
    for kind in KINDS:
        d = root / "entries" / kind
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.md")):
            m = MARK.match(p.read_bytes().decode("utf-8", "replace").split("\n")[0])
            if not m or m.group("id") != p.stem:
                bad += 1
    print("files whose stem still != marker id : %d" % bad)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
