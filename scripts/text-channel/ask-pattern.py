#!/usr/bin/env python3
"""ask-pattern.py - what does an ask body actually look like in sms_log?

The LIKE '%CFO [ask-%' pattern returned zero, but asks were certainly sent ("CFO [ask-1792395018]:
what was 25.00 at api"). Print the real bodies and their bytes so the pattern can be written against
what is there rather than what was assumed.
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
rows = c.execute("""
select created_at, status, body from sms_log
where to_number='+18483897895' and direction='outbound'
  and (body like '%ask-%' or body like '%CFO%')
order by created_at desc limit 8
""").fetchall()
print("rows containing 'ask-' or 'CFO': %d" % len(rows))
for when, status, body in rows:
    b = (body or "")
    print("  %s %-10s len=%-4d %r" % (when[:19], status, len(b), b[:70]))
print()
print("count with the exact substring 'CFO [ask-':",
      c.execute("""select count(*) from sms_log where to_number='+18483897895'
                   and direction='outbound'
                   and instr(body, 'CFO [ask-') > 0""").fetchone()[0])
print("count with '[' and 'ask-' anywhere:",
      c.execute("""select count(*) from sms_log where to_number='+18483897895'
                   and direction='outbound'
                   and instr(body, 'ask-') > 0""").fetchone()[0])
