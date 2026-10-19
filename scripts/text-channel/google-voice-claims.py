#!/usr/bin/env python3
"""google-voice-claims.py - 353 rows claim a send; is there any text at all?

The one body that looked wrong after correcting the prefix-matching artefact. Match by TIME, not by
body text, so a templated or re-prefixed send cannot hide.
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row
OWNER = "+18483897895"

rows = c.execute("""
select id, status, created_at, sent_at, send_attempts, last_send_error
from owner_message_queue
where body like 'Google Voice monitoring is blind for account 0%'
order by id desc limit 6
""").fetchall()

print("newest queue rows for the Google Voice body")
for q in rows:
    print("  #%s %-10s created=%s sent_at=%s attempts=%s err=%s"
          % (q["id"], q["status"], str(q["created_at"])[:19], str(q["sent_at"])[:19],
             q["send_attempts"], (q["last_send_error"] or "-")[:40]))
print()

probe = [r for r in rows if r["sent_at"]]
for q in probe[:4]:
    hits = c.execute("""
        select created_at, status, substr(body,1,80) b from sms_log
        where to_number=? and abs(julianday(created_at)-julianday(?)) < 0.02
        limit 3
    """, (OWNER, q["sent_at"])).fetchall()
    print("around claim %s (#%s):" % (str(q["sent_at"])[:19], q["id"]))
    if not hits:
        print("   NO sms_log row within ~30 minutes")
    for h in hits:
        print("   %s %-10s %s" % (str(h["created_at"])[11:19], h["status"], h["b"]))
    print()

print("total rows for this body by status:")
for r in c.execute("""
    select status, count(*), min(created_at), max(created_at)
    from owner_message_queue where body like 'Google Voice monitoring is blind for account 0%'
    group by 1 order by 2 desc
"""):
    print("   %-24s n=%-4d %s .. %s" % (r[0], r[1], str(r[2])[:10], str(r[3])[:10]))
