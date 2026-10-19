#!/usr/bin/env python3
"""are-duplicate-categories-orphans.py - is the duplication harmless once the choice is stable?

If every duplicate name has ONE id in use and the others used zero times, then the ambiguity was
purely a nondeterministic tie-break, and choosing "the id with the most filings" always selects
the real one. If some duplicates are BOTH in use, then two visibly identical categories are really
splitting the books and that is a bookkeeping decision for the owner.
"""
import sqlite3

a = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)

rows = a.execute("""
select c.name, c.id,
       (select count(*) from transaction_categories tc where tc.category_id = c.id) used
from categories c
order by c.name, used desc
""").fetchall()

by_name = {}
for name, cid, used in rows:
    by_name.setdefault((name or "").lower(), []).append((cid, used, name))

orphan_names = []
split_names = []
for key, entries in by_name.items():
    if len(entries) < 2:
        continue
    used = [e[1] for e in entries]
    if sum(1 for u in used if u > 0) <= 1:
        orphan_names.append((key, entries))
    else:
        split_names.append((key, entries))

print("duplicate names: %d" % (len(orphan_names) + len(split_names)))
print()
print("== ALL alternates unused (harmless once the choice is deterministic): %d" % len(orphan_names))
for key, entries in sorted(orphan_names):
    e = sorted(entries, key=lambda x: -x[1])
    print("   %-46s keeper used %4d | orphans %s"
          % (e[0][2][:46], e[0][1], ", ".join("%s(0)" % x[0][:8] for x in e[1:])))
print()
print("== BOTH in use - the books really are split: %d" % len(split_names))
for key, entries in sorted(split_names):
    e = sorted(entries, key=lambda x: -x[1])
    print("   %-46s %s" % (e[0][2][:46],
                           " | ".join("%s used %d" % (x[0][:8], x[1]) for x in e)))
