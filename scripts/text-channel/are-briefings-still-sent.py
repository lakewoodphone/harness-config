#!/usr/bin/env python3
"""are-briefings-still-sent.py - is the class that mutilates 24% of the channel still running?

281 of the 295 over-length bodies are morning/evening briefings. He banned them twice, and the first
scorecard in this programme measured them 4/4 and 2/2 dead. Before changing anything: are they still
being produced, and when did the last one go out?
"""
import sqlite3
from collections import Counter

m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
rows = m.execute("""
select coalesce(date_sent_utc, date_sent) AS sentwhen, coalesce(status,'') AS st, body
from messages
where direction='outbound' and to_number like '%18483897895%'
  and (lower(coalesce(body,'')) like '%briefing%')
order by 1
""").fetchall()
print("messages whose body mentions a briefing: %d" % len(rows))
if rows:
    print("  first: %s" % str(rows[0][0])[:19])
    print("  last : %s" % str(rows[-1][0])[:19])
    by_month = Counter(str(r[0])[:7] for r in rows)
    for k in sorted(by_month):
        print("    %-8s %3d %s" % (k, by_month[k], "=" * min(by_month[k], 30)))

a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
n = a.execute("""select count(*), min(created_at), max(created_at) from sms_log
                 where to_number='+18483897895' and lower(coalesce(body,'')) like '%briefing%'""").fetchone()
print()
print("in the app's ledger: %d briefing text(s), %s .. %s" % (n[0], str(n[1])[:10], str(n[2])[:10]))

print()
print("== and the tick that would send them - is it still configured?")
import subprocess
out = subprocess.run(["bash", "-lc",
                      "systemctl is-active company-api; "
                      "grep -c '_maybe_send_morning_briefing' /opt/company/app/agent_bus.py"],
                     capture_output=True, text=True)
print("  " + (out.stdout or "").strip().replace("\n", " | "))

