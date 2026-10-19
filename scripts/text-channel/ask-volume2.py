#!/usr/bin/env python3
"""ask-volume2.py - corrected: find the real ask marker and the real ask schema."""
import sqlite3

a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c = sqlite3.connect("file:/root/accounting-data/live/accounting.db?mode=ro", uri=True)

print("== what an owner-directed question actually looks like in sms_log")
for r in a.execute("""
select created_at, agent_id, status, substr(replace(body,char(10),' '),1,90)
from sms_log
where to_number='+18483897895' and direction='outbound'
  and (body like '%CFO%' or body like '%ask-%')
order by created_at desc limit 8
"""):
    print("   %s %-18s %-10s %s" % (r[0][:16], str(r[1])[:18], r[2], r[3]))

print()
print("== questions by day, last 21 days, using the marker that is actually there")
rows = a.execute("""
select substr(created_at,1,10) d, count(*)
from sms_log
where to_number='+18483897895' and direction='outbound'
  and (body like '%CFO%' or body like '%ask-%')
  and status in ('delivered','sent')
  and created_at >= date('now','-21 day')
group by 1 order by 1
""").fetchall()
tot = 0
for d, n in rows:
    tot += n
    print("   %s  %2d %s" % (d, n, "=" * n))
print("   %d questions reached him in 21 days" % tot)

print()
print("== the cfo ask store schema, then its real states")
s = sqlite3.connect("file:/root/.cfo-asks/asks.db?mode=ro", uri=True)
cols = [r[1] for r in s.execute("pragma table_info(ask)")]
print("   columns:", cols)
for cand in ("status", "state", "answered_at", "answer"):
    if cand in cols:
        print("   by %s:" % cand)
        for r in s.execute("select %s, count(*) from ask group by 1 order by 2 desc"
                           % cand):
            print("      %-22s %d" % (str(r[0])[:22], r[1]))
