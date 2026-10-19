#!/usr/bin/env python3
"""how-many-questions-a-day.py - what the caps allow, and what actually went out.

He has said "one item at a time" more than once. The CFO's caps live in cron and in the asker. This
measures the real rate: questions per day, over the life of the channel, and the busiest days, so a
cap can be set against evidence rather than taste.
"""
import sqlite3

AUTH = "/root/authority.db"
c = sqlite3.connect("file:%s?mode=ro" % AUTH, uri=True)

print("== CFO questions delivered, by day (top 12 busiest)")
rows = c.execute("""
select substr(created_at,1,10) d, count(*) n
from sms_log
where to_number='+18483897895' and direction='outbound'
  and status in ('delivered','sent') and body like '%CFO [ask-%'
group by 1 order by n desc limit 12
""").fetchall()
for d, n in rows:
    print("   %s  %2d %s" % (d, n, "=" * n))

print()
print("== distribution of questions per active day")
dist = c.execute("""
select n, count(*) days from (
  select substr(created_at,1,10) d, count(*) n
  from sms_log
  where to_number='+18483897895' and direction='outbound'
    and status in ('delivered','sent') and body like '%CFO [ask-%'
  group by 1) group by n order by n
""").fetchall()
for n, days in dist:
    print("   %d question(s) on %d day(s)" % (n, days))
total_days = sum(d for _, d in dist)
total_q = sum(n * d for n, d in dist)
print("   %d questions over %d active days (mean %.1f)"
      % (total_q, total_days, total_q / total_days if total_days else 0))

print()
print("== all owner-directed texts, by day, last 14 days (the whole channel, not just asks)")
for d, n in c.execute("""
select substr(created_at,1,10) d, count(distinct coalesce(twilio_sid,id)) n
from sms_log
where to_number='+18483897895' and direction='outbound'
  and status in ('delivered','sent') and created_at >= date('now','-14 day')
group by 1 order by 1
""").fetchall():
    print("   %s  %2d %s" % (d, n, "=" * n))

print()
print("== the caps currently in force (cron)")
import subprocess
out = subprocess.run(["bash", "-lc",
                      "crontab -l 2>/dev/null | grep -E 'cfo-shift|cfo-ask' | head -4"],
                     capture_output=True, text=True)
for line in (out.stdout or "").splitlines():
    print("   " + line.strip()[:150])
