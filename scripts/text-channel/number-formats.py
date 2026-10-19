#!/usr/bin/env python3
"""number-formats.py - every spelling of his number in sms_log, and what each holds.

An exact-string filter on `to_number='+18483897895'` found zero CFO questions while a whole-table
scan found two. That means the table stores more than one spelling of the same number, and any
measurement that filters on one spelling silently omits the others.

This lists every distinct to_number that contains his digits, with a row count and how many carry a
CFO ask.
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)

print("== every distinct to_number containing 18483897895")
rows = c.execute("""
select coalesce(to_number,'(null)') tn, count(*) n,
       sum(case when instr(coalesce(body,''),'CFO [ask-') > 0 then 1 else 0 end) asks,
       sum(case when direction='outbound' then 1 else 0 end) outb
from sms_log
where replace(replace(replace(coalesce(to_number,''),'+',''),'-',''),' ','') like '%18483897895%'
group by 1 order by n desc
""").fetchall()
for tn, n, asks, outb in rows:
    print("   %-22r rows=%-5d outbound=%-5d asks=%d" % (tn, n, outb, asks))

print()
print("== the two ask rows, in full")
for r in c.execute("""
select id, created_at, coalesce(to_number,'(null)'), coalesce(from_number,'(null)'),
       status, coalesce(agent_id,'-'), substr(body,1,60)
from sms_log where instr(coalesce(body,''),'CFO [ask-') > 0
"""):
    print("   id=%s %s to=%r from=%r %s agent=%s | %s"
          % (r[0], r[1][:19], r[2], r[3], r[4], r[5], r[6]))

print()
print("== how many outbound rows have a to_number that is NOT the canonical spelling?")
canon = c.execute("""select count(*) from sms_log
                     where to_number='+18483897895' and direction='outbound'""").fetchone()[0]
anyform = c.execute("""select count(*) from sms_log
                       where replace(replace(replace(coalesce(to_number,''),'+',''),'-',''),' ','')
                             like '%18483897895%' and direction='outbound'""").fetchone()[0]
print("   canonical '+18483897895': %d outbound" % canon)
print("   any spelling            : %d outbound  (difference %d)" % (anyform, anyform - canon))
