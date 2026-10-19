#!/usr/bin/env python3
"""is-the-guard-inert.py - a bypass that always fires is not a bypass, it is the default.

The relay's quiet hours suppress sends between 23:00 and 07:30 unless the message is urgent,
critical or stuck, is marked as a reply, or he has texted inside the hour. If every sender passes
`urgency='urgent'` - or nothing sets a class - the guard never fires and looks installed.

This reads the relay's own attempt rows: what urgency and class every door actually passes, and
how many historical 23:00-07:30 sends would still pass the guard today.
"""
import sqlite3
from collections import Counter
from datetime import datetime, timedelta, timezone

DB = "/root/.owner-text/relay.db"
c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
c.row_factory = sqlite3.Row

cols = [r[1] for r in c.execute("pragma table_info(attempt)")]
print("attempt columns: %s" % ",".join(cols))
print()

print("== urgency passed by each door/subsystem (all attempts)")
for r in c.execute("""
select coalesce(urgency,'(null)') u, coalesce(door,'(none)') d, count(*) n
from attempt group by 1,2 order by n desc limit 12
"""):
    print("   %-10s %-22s %d" % (r["u"], r["d"], r["n"]))

print()
print("== class_hint (the other bypass: 'reply')")
for r in c.execute("""
select coalesce(class_hint,'(null)') h, count(*) n from attempt group by 1 order by n desc
"""):
    print("   %-14s %d" % (r["h"], r["n"]))

print()
print("== verdicts recorded so far (has the guard ever fired?)")
for r in c.execute("select coalesce(verdict,'(null)') v, count(*) n from attempt group by 1 "
                   "order by n desc"):
    print("   %-12s %d" % (r["v"], r["n"]))

print()
print("== of the DELIVERED owner texts between 23:00 and 07:30 local, how many would the")
print("   guard pass today because of a bypass?")
try:
    import zoneinfo
    NY = zoneinfo.ZoneInfo("America/New_York")
    print("   zoneinfo AVAILABLE on this host: %s -> %s" % (True, datetime.now(NY).isoformat()))
except Exception as exc:
    NY = None
    print("   zoneinfo UNAVAILABLE (%s: %s) - the fixed-offset fallback is what runs"
          % (type(exc).__name__, exc))

a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
quiet = 0
would_pass_urgent = 0
for r in a.execute("""
select created_at, body from sms_log
where to_number='+18483897895' and direction='outbound'
  and status in ('delivered','sent') and created_at >= '2026-06-01'
"""):
    try:
        at = datetime.fromisoformat(str(r[0]).replace("Z", "+00:00"))
    except ValueError:
        continue
    local = at.astimezone(NY) if NY else at
    if local.hour >= 23 or local.hour < 7 or (local.hour == 7 and local.minute < 30):
        quiet += 1
        body = (r[1] or "").lower()
        if "urgent" in body or "🚨" in body or "critical" in body:
            would_pass_urgent += 1
print("   quiet-window texts since 2026-06-01 : %d" % quiet)
print("   of those, bodies that SAY urgent    : %d" % would_pass_urgent)
print("   (urgency is passed by the CALLER, not read from the body, so the second number is"
      " only a hint)")
