#!/usr/bin/env python3
"""category-vocabulary.py - do the words the code writes actually exist in the ledger?

`category_from()` returns his own words lowercased - "personal", "business", "shop supplies",
"Gas & Fuel", "Groceries" - and `category_id_for()` returns "" for a name the categories table
does not hold, so the charge is never filed while the rung reports success. This checks each word
the code can emit against the table, and reports duplicate names, which make a name->id lookup
ambiguous.

Read-only.
"""
import sqlite3

a = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)

names = [r[0] for r in a.execute("select name from categories")]
by_lower = {}
for n in names:
    if n:
        by_lower.setdefault(n.lower(), []).append(n)

print("== duplicates: one NAME, several ids")
dupes = {k: v for k, v in by_lower.items() if len(v) > 1}
ids = {}
for r in a.execute("select id, name from categories"):
    if r[1]:
        ids.setdefault(r[1].lower(), []).append(r[0])
for k in sorted(dupes):
    print("   %-40s %d ids  %s" % (k, len(ids[k]), ids[k][:3]))
print("   %d duplicate names out of %d categories" % (len(dupes), len(names)))

print()
print("== the words category_from() can emit")
CANDIDATES = ("personal", "business", "shop supplies", "Gas & Fuel", "Groceries",
              "unknown", "Fees & Adjustments", "Parking & Tolls", "Subscriptions",
              "Software & Online Services", "Insurance")
for word in CANDIDATES:
    hit = by_lower.get(word.lower())
    if hit:
        print("   %-30s EXISTS  %r" % (word, hit[0]))
    else:
        near = [n for n in names if n and word.split()[0].lower() in n.lower()][:3]
        print("   %-30s MISSING near=%s" % (word, near))
