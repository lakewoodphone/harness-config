#!/usr/bin/env python3
"""queue-claims-sent.py - do the queue's "sent" rows correspond to any text that left?

MEASURED: `owner_message_queue` holds 353 rows in status 'sent' for one body ("Google Voice
monitoring is blind for account 0"), and a first pass matched 750 of 792 'sent' rows against
`sms_log` on a 40-character body prefix and found nothing. A prefix match is exactly the kind of
measurement that produces a fake catastrophe - a templated or trimmed body would miss it.

So this samples real rows and looks for ANY sms_log row within ~15 minutes of the claim, and prints
both bodies. Read-only.
"""
import sqlite3

AUTH = "/root/authority.db"
OWNER = "+18483897895"
c = sqlite3.connect("file:%s?mode=ro" % AUTH, uri=True)
c.row_factory = sqlite3.Row

rows = c.execute("""
select id, body, sent_at from owner_message_queue
where status='sent' and sent_at is not null
order by sent_at desc limit 8
""").fetchall()

print("sampling the newest %d queue rows that claim to be sent" % len(rows))
print()
matched = 0
for q in rows:
    body = " ".join((q["body"] or "").split())[:70]
    hits = c.execute("""
        select created_at, status, substr(body,1,70) b from sms_log
        where to_number=? and abs(julianday(created_at)-julianday(?)) < 0.01
        limit 2
    """, (OWNER, q["sent_at"])).fetchall()
    print("queue #%s claim=%s" % (q["id"], str(q["sent_at"])[:19]))
    print("   QUEUE : %s" % body)
    if hits:
        matched += 1
        for h in hits:
            print("   SMSLOG: %s %-10s %s" % (str(h["created_at"])[11:19], h["status"], h["b"]))
    else:
        print("   SMSLOG: nothing within ~15 minutes")
    print()

print("rows with ANY sms_log activity nearby: %d of %d" % (matched, len(rows)))
print()
print("For scale, the queue overall:")
for r in c.execute("""
    select status, count(*) n from owner_message_queue group by 1 order by n desc
"""):
    print("   %-24s %d" % (r["status"], r["n"]))
