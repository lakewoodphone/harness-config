#!/usr/bin/env python3
"""do-cfo-asks-reach-sms-log.py - the class he complains about may not be in the audit table.

`sms_log` holds ZERO rows containing the substring `ask-`, yet `owner_text_turn` holds CFO question
bodies like "CFO [ask-1792395018]: what was 25.00 at api on 16 Jun", and he replied to them on
2026-10-19 at 07:30 and 13:37. If those sends are not in sms_log, then every figure measured from
sms_log - the replay, the conformance census, "482 texts reached him" - excludes the single largest
class of complaint.

This settles it: look for the same question by its own words, in any status, and look at who was
sending around those timestamps.
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
OWNER = "+18483897895"

print("== look for the ask CONTENT, without the reference")
for pat in ("%what was 25.00 at%", "%what was 57.95%", "%what was 135.33%",
            "%what was 66.54%", "%One line and I'll file it%"):
    n = c.execute("""select count(*) from sms_log
                     where to_number=? and direction='outbound' and body like ?""",
                  (OWNER, pat)).fetchone()[0]
    print("   %-30s %d row(s)" % (pat, n))

print()
print("== what was sending in the 10 minutes around the 2026-10-19 07:30 ask")
for r in c.execute("""
    select created_at, direction, status, coalesce(agent_id,'-'), substr(replace(body,char(10),' '),1,60)
    from sms_log
    where (to_number=? or from_number=?)
      and abs(julianday(created_at)-julianday('2026-10-19T07:30:18+00:00')) < 0.01
    order by created_at
""", (OWNER, OWNER)):
    print("   %s %-8s %-10s %-18s | %s" % (r[0][11:19], r[1], r[2], str(r[3])[:18], r[4]))

print()
print("== and around 2026-10-19 13:37")
for r in c.execute("""
    select created_at, direction, status, coalesce(agent_id,'-'), substr(replace(body,char(10),' '),1,60)
    from sms_log
    where (to_number=? or from_number=?)
      and abs(julianday(created_at)-julianday('2026-10-19T13:37:12+00:00')) < 0.01
    order by created_at
""", (OWNER, OWNER)):
    print("   %s %-8s %-10s %-18s | %s" % (r[0][11:19], r[1], r[2], str(r[3])[:18], r[4]))

print()
print("== the turn ledger's ask rows and whether a matching sms_log row exists")
for r in c.execute("""select sent_at, sid, substr(body,1,50) from owner_text_turn
                      where body like 'CFO [ask-%' order by sent_at desc limit 5"""):
    hit = c.execute("""select count(*) from sms_log where to_number=?
                       and instr(body, ?) > 0""", (OWNER, (r[2] or "")[:30])).fetchone()[0]
    print("   %s sid=%s smslog_match=%d | %s" % (r[0][:19], str(r[1])[:14], hit, r[2][:50]))
