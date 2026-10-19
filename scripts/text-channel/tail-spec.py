#!/usr/bin/env python3
"""tail-spec.py - what do the UNANSWERED asks' charges actually look like on the statement?

The ask store holds the merchant, amount, date and transaction id for every question the CFO
decided was worth his attention. 57 of them were never resolved. If a statement descriptor
already determines the kind of charge, that question was never worth asking - so this prints the
descriptor of every unresolved charge, to decide which are answerable without him.

Read-only.
"""
import sqlite3

s = sqlite3.connect("file:/root/.cfo-asks/asks.db?mode=ro", uri=True)
a = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)

rows = s.execute("""
select coalesce(merchant,'(none)'), merchant_key, amount_cents, transaction_date,
       transaction_id, coalesce(answer,'')
from ask
where answered_at is null
order by transaction_date desc
""").fetchall()
print("unresolved asks: %d" % len(rows))
print()
seen = set()
for merchant, key, cents, date, txn, answer in rows:
    sig = (key or merchant or "")
    desc = ""
    if txn:
        r = a.execute(
            "select coalesce(normalized_description,''), coalesce(description,''), "
            "coalesce(merchant_name,'') from transactions where id=?", (txn,)).fetchone()
        if r:
            desc = r[0] or r[1] or r[2]
    flag = "" if sig in seen else "NEW"
    seen.add(sig)
    print("  %-30s %9s  %-10s  %-6s | %s"
          % (str(merchant)[:30], ("%.2f" % ((cents or 0) / 100.0)), str(date)[:10],
             flag, str(desc)[:58]))

print()
print("distinct merchants in the unresolved tail: %d" % len(seen))
