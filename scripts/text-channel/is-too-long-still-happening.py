#!/usr/bin/env python3
"""is-too-long-still-happening.py - is the over-length retry storm live or history?

1,273 `too_long` refusals, but the count is dominated by a handful of bodies retried hundreds of
times: 842 for a 321-char Fishman reminder, 291 for an 811-char Topgolf reminder. That is a retry
storm, not 1,273 lost messages.

Two questions decide whether there is work here:
  1. when was the LAST too_long refusal?
  2. did the words that were refused eventually reach him, or not at all?
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

print("== the last ten too_long refusals")
for r in c.execute("""select created_at, chars, coalesce(body_head,'') h
                      from owner_text_decision where code='too_long'
                      order by created_at desc limit 10"""):
    print("   %s chars=%-5s %s" % (r[0][:19], r[1], str(r[2])[:60]))

print()
print("== did those bodies EVER reach him?")
for label, head in (("Fishman 300DDR 321", "Check 300DDR for Fishman"),
                    ("Topgolf 811", "CALL TOPGOLF EDISON GUEST CARE"),
                    ("NJ DOL 390", "NJ DOL separation request"),
                    ("NY Tolls 378", "New York Tolls by Mail bill"),
                    ("Elantra 455", "The Elantra")):
    n = m.execute("""select count(*) from messages where direction='outbound'
                     and to_number like '%18483897895%'
                     and coalesce(status,'') in ('delivered','sent')
                     and instr(coalesce(body,''),?) > 0""", (head,)).fetchone()[0]
    print("   %-24s delivered %d time(s)" % (label, n))

print()
print("== and how many too_long in the last 7 days?")
for days in (1, 7, 30):
    n = c.execute("""select count(*) from owner_text_decision where code='too_long'
                     and created_at >= datetime('now', ?)""", ("-%d day" % days,)).fetchone()[0]
    print("   last %-2d day(s): %d" % (days, n))
