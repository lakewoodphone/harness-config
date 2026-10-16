#!/usr/bin/env python3
"""51-dedupe-sim.py -- simulate `journal.py dedupe` on the merged tree EXACTLY as cmd_dedupe
computes it, and report the archive destination of every move BEFORE anything is applied.

cmd_dedupe (tools/journal.py, cmd_dedupe) does, per group, after sorting the group by
(num_of(id_full), date, id_full) and keeping group[0]:

    dest = JOURNAL / "archive" / "duplicates" / dup["kind"] / (dup["id_full"] + ".md")
    shutil.move(_path_of(dup["file"]), dest)

There is no `while dest.exists()` loop -- unlike cmd_repair_ids, which has one. Two surplus
copies of ONE id therefore land on ONE path and the second move silently overwrites the first.
This script computes that destination for every planned move and says whether any two moves
collide, so the decision to run --apply is made on evidence and not on hope.
"""
from __future__ import annotations

import collections
import importlib.util
import pathlib
import sys

ROOT = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "/root/work/r7/merged-journal")
TOOL = ROOT / "tools" / "journal.py"

spec = importlib.util.spec_from_file_location("jm", TOOL)
jm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(jm)
jm.JOURNAL = ROOT

entries, problems = jm.load_entries()
groups = collections.defaultdict(list)
for e in entries:
    groups[jm.identity_of(e["kind"], e["heading"], e["body"])].append(e)

moves = []
keeps = []
for ident, group in sorted(groups.items(), key=lambda kv: (kv[1][0]["kind"], kv[1][0]["id_full"])):
    if len(group) < 2:
        continue
    group.sort(key=lambda e: (jm.num_of(e["id_full"]), e.get("date") or "", e["id_full"]))
    keep = group[0]
    keeps.append((ident, keep))
    for dup in group[1:]:
        dest = ROOT / "archive" / "duplicates" / dup["kind"] / (dup["id_full"] + ".md")
        moves.append({"group": ident, "id": dup["id_full"], "file": dup["file"],
                      "dest": str(dest.relative_to(ROOT)),
                      "keep": keep["id_full"], "keep_file": keep["file"]})

print("entries=%d  dedupe groups>=2=%d  planned moves=%d"
      % (len(entries), len(keeps), len(moves)))
by_dest = collections.defaultdict(list)
for m in moves:
    by_dest[m["dest"]].append(m)
clash = {d: v for d, v in by_dest.items() if len(v) > 1}
print("distinct destinations=%d  DESTINATIONS THAT WOULD BE OVERWRITTEN=%d"
      % (len(by_dest), len(clash)))
print("")
print("-- move plan --")
for m in moves:
    print("  %-10s %-46s -> %s" % (m["id"], m["file"], m["dest"]))
print("")
if clash:
    print("!! CLOBBER: these moves share a destination; the first file moved is DESTROYED")
    for d, v in sorted(clash.items()):
        print("   dest %s" % d)
        for m in v:
            print("      %s  <- %s" % (m["id"], m["file"]))
    lost = sum(len(v) - 1 for v in clash.values())
    print("   files that would be destroyed by `dedupe --apply`: %d" % lost)
    print("")
    print("SAFE ALTERNATIVE: perform these %d move(s) by hand first -- same destination for the"
          % len(moves))
    print("first, a collision-free name for the rest -- and record the same alias row, then run")
    print("dedupe unmodified for the remaining %d." % (len(moves) - sum(len(v) for v in clash.values())))
else:
    print("OK: every planned move has a unique destination; `dedupe --apply` cannot overwrite.")
sys.exit(0)
