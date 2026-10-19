#!/usr/bin/env python3
"""tail-resolution2.py - three buckets, because "solved" is two different things.

`solved=True` covers both "we know the merchant and what kind of charge it was" (FILABLE) and "we
recognise the merchant but nobody has ever said what it was for" (IDENTIFIED). Both stop the
question; only the first can be filed. Reporting them as one number hides the second.

Read-only.
"""
import sqlite3
import sys

sys.path.insert(0, "/root/bin")
import merchant_resolve as MR  # noqa: E402

acct = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)
known = {(r[0] or "").lower() for r in acct.execute("select name from categories")}
acct.close()

s = sqlite3.connect("file:/root/.cfo-asks/asks.db?mode=ro", uri=True)
rows = s.execute("""
select coalesce(merchant,''), coalesce(merchant_key,''), count(*), sum(amount_cents),
       min(transaction_date)
from ask where answered_at is null group by 1,2 order by 4 desc, 1
""").fetchall()

filable, identified, unsolved = [], [], []
for merchant, key, n, cents, when in rows:
    probe = key or merchant
    if not probe:
        continue
    try:
        r = MR.resolve(probe, merchant=merchant or None, research=False)
    except Exception:                                          # noqa: BLE001
        continue
    cat = str(r.get("category") or "").strip()
    rec = (probe, cat, r.get("method") or r.get("source"), float(r.get("confidence") or 0),
           n, (cents or 0) / 100.0, str(when or "")[:10])
    if not r.get("solved"):
        unsolved.append(rec)
    elif cat and cat.lower() in known:
        filable.append(rec)
    else:
        identified.append(rec)

print("distinct merchants in the unresolved tail: %d" % (len(rows)))
print("  FILABLE  (solved AND a category the ledger holds) : %d" % len(filable))
print("  IDENTIFIED (merchant known, no category)          : %d" % len(identified))
print("  UNSOLVED (nothing in our records at all)          : %d" % len(unsolved))
print()
print("== IDENTIFIED: no longer asked, but still cannot be filed")
for probe, cat, method, conf, n, dollars, when in sorted(identified, key=lambda x: -x[5]):
    print("   %-34s %-22s n=%d total=%8.2f" % (probe[:34], str(method)[:22], n, dollars))
print()
print("== UNSOLVED: this is the honest residue - only these still deserve a question")
for probe, cat, method, conf, n, dollars, when in sorted(unsolved, key=lambda x: -x[5]):
    print("   %-34s %s  n=%d total=%8.2f" % (probe[:34], when, n, dollars))
