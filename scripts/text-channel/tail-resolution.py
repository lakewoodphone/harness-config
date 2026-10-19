#!/usr/bin/env python3
"""tail-resolution.py - which unresolved asks can the resolver answer TODAY?

The 57 unresolved asks are the specification. Run the live resolver over every distinct merchant in
that tail and report, per merchant, whether it is solved now and by which rung. What is unsolved
after today's work is either (a) a missing definitional rule, or (b) genuinely his call.

Read-only.
"""
import sqlite3
import sys

sys.path.insert(0, "/root/bin")
import merchant_resolve as MR  # noqa: E402

s = sqlite3.connect("file:/root/.cfo-asks/asks.db?mode=ro", uri=True)
rows = s.execute("""
select coalesce(merchant,''), coalesce(merchant_key,''), count(*), sum(amount_cents)
from ask where answered_at is null group by 1,2 order by 3 desc, 1
""").fetchall()

solved, unsolved = [], []
for merchant, key, n, cents in rows:
    probe = key or merchant
    if not probe:
        continue
    try:
        r = MR.resolve(probe, merchant=merchant or None, research=False)
    except Exception as exc:                                   # noqa: BLE001
        print("  ERROR %-32s %s" % (probe[:32], exc))
        continue
    rec = (probe, r.get("category"), r.get("method") or r.get("source"),
           float(r.get("confidence") or 0), n, (cents or 0) / 100.0,
           bool(r.get("solved")))
    (solved if rec[6] else unsolved).append(rec)

print("distinct merchants in the unresolved tail: %d" % len(rows))
print("  resolvable now : %d" % len(solved))
print("  still unsolved : %d" % len(unsolved))
print()
print("== resolvable now (these should never have been asked)")
for probe, cat, method, conf, n, dollars, _ in sorted(solved, key=lambda x: -x[5]):
    print("   %-34s -> %-28s %-22s conf=%.2f  n=%d  total=%.2f"
          % (probe[:34], str(cat)[:28], str(method)[:22], conf, n, dollars))
print()
print("== still unsolved (the honest residue, or a missing definition)")
for probe, cat, method, conf, n, dollars, _ in sorted(unsolved, key=lambda x: -x[5]):
    print("   %-34s n=%d  total=%.2f" % (probe[:34], n, dollars))
