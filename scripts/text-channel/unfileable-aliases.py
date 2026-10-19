#!/usr/bin/env python3
"""unfileable-aliases.py - how much learned knowledge names a category the ledger does not hold?

An alias row was learned for "american professional" with category "personal". "personal" is not
in the categories table - the nearest name is "Unidentified Personal Spending". So the row
resolves a charge as solved and files nothing, and the question it was learned from can come back.

If that is a one-off it is a curiosity. If it is a pattern, the alias store is full of answers
that cannot be filed. Read-only.
"""
import sqlite3

a = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)
names = {(r[0] or "").lower() for r in a.execute("select name from categories")}

s = sqlite3.connect("file:/root/.cfo-asks/aliases.db?mode=ro", uri=True)
rows = s.execute("select merchant_key, entity, category, source, learned_at from alias").fetchall()

good, bad, blank = [], [], []
for key, entity, cat, source, learned in rows:
    c = (cat or "").strip()
    if not c:
        blank.append((key, entity, learned))
    elif c.lower() in names:
        good.append((key, c, learned))
    else:
        bad.append((key, entity, c, learned))

print("learned aliases: %d" % len(rows))
print("  filed category that EXISTS      : %d" % len(good))
print("  category MISSING from the ledger: %d" % len(bad))
print("  no category at all              : %d" % len(blank))
print()
if bad:
    print("== the unfilable ones")
    for key, entity, cat, learned in sorted(bad, key=lambda r: str(r[3])):
        print("   %-38s category=%-24s learned %s" % (str(key)[:38], str(cat)[:24],
                                                      str(learned)[:10]))
print()
print("== categories the missing ones use, and how often")
from collections import Counter
for cat, n in Counter(str(b[2]).lower() for b in bad).most_common(12):
    print("   %-28s %d" % (cat, n))
