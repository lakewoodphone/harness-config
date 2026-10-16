#!/usr/bin/env python3
"""50-preflight.py -- ask the merged tree, using journal.py's OWN identity function, whether
`dedupe --apply` is safe to run on it.

The question is narrow and it is the one the clobber proof raises. cmd_dedupe writes every
surplus copy of one group to

    archive/duplicates/<kind>/<dup id_full>.md

with NO collision-avoidance loop. So a group that contains TWO OR MORE entries carrying the
SAME id_full will lose one file to the overwrite. That is a data-loss state and this script
exists to detect it BEFORE --apply, not after.

It reports:
  * entries parsed and problems
  * ids carried by more than one file, and the number of distinct bodies per id
  * dedupe groups of size >= 2 (the real work dedupe would do)
  * the subset of those groups where two members share an id_full  <-- CLOBBER RISK
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
print("tool        : %s" % TOOL)
print("tool sha256 : %s" % __import__("hashlib").sha256(TOOL.read_bytes()).hexdigest())
print("root        : %s" % ROOT)
print("entries parsed : %d   problems: %d" % (len(entries), len(problems)))
for p in problems[:10]:
    print("   PROBLEM %s" % p)

by_id = collections.defaultdict(list)
for e in entries:
    by_id[(e["kind"], e["id_full"])].append(e)
multi = {k: v for k, v in by_id.items() if len(v) > 1}
conflict = {k: v for k, v in multi.items() if len({e["hash"] for e in v}) > 1}
print("distinct (kind,id) : %d" % len(by_id))
print("ids carried by >1 file : %d" % len(multi))
print("  of those, differing content : %d" % len(conflict))

groups = collections.defaultdict(list)
for e in entries:
    groups[jm.identity_of(e["kind"], e["heading"], e["body"])].append(e)
dup_groups = {k: v for k, v in groups.items() if len(v) > 1}
print("dedupe groups size>=2 : %d  (surplus copies = %d)"
      % (len(dup_groups), sum(len(v) - 1 for v in dup_groups.values())))

risky = []
for k, v in dup_groups.items():
    c = collections.Counter(e["id_full"] for e in v)
    same = [i for i, n in c.items() if n > 1]
    if same:
        risky.append((k, v, same))
print("")
print("CLOBBER-RISK groups (>=2 members sharing one id_full) : %d" % len(risky))
for k, v, same in risky[:20]:
    print("   kind=%s ids=%s" % (k[0], same))
    for e in v:
        print("      %-10s %s" % (e["id_full"], e["file"]))
if not risky:
    print("   (none -- every surplus copy in a dedupe group has a distinct id_full,")
    print("    so archive/duplicates/<id>.md is a unique destination for each move)")
print("")
print("ids with >1 distinct body after merge : %d  (expect 364)"
      % len(conflict))
