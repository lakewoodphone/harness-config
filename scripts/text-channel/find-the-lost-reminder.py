#!/usr/bin/env python3
"""find-the-lost-reminder.py - one reminder was refused 842 times and never arrived.

Every other over-length reminder eventually reached him once the body fitted. This one did not:
"Check 300DDR for Fishman tickets 74114", 321 characters, 842 refusals, delivered 0 times.

So the question is not about the gate - it is whether the WORK that reminder names is still
outstanding. If it is, he has never been told, and that is the only real casualty of the 1,273.
"""
import sqlite3

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("== the reminder rows that mention it")
try:
    for r in c.execute("""select id, coalesce(message,'') m, status, scheduled_time, source,
                                 length(coalesce(message,'')) len
                          from reminders
                          where instr(lower(coalesce(message,'')), 'fishman') > 0
                             or instr(lower(coalesce(message,'')), '300ddr') > 0
                             or instr(lower(coalesce(message,'')), '74114') > 0
                          order by id desc limit 6"""):
        print("   #%s %-10s sched=%s len=%s src=%s" % (r["id"], r["status"],
                                                        str(r["scheduled_time"])[:19], r["len"],
                                                        r["source"]))
        print("      %s" % " ".join((r["m"] or "").split())[:150])
except Exception as exc:                                       # noqa: BLE001
    print("   reminders table: %s" % exc)

print()
print("== any task that mentions it")
try:
    for r in c.execute("""select id, status, substr(coalesce(description,''),1,110)
                          from tasks
                          where instr(lower(coalesce(description,'')), 'fishman') > 0
                             or instr(lower(coalesce(description,'')), '74114') > 0
                          order by id desc limit 5"""):
        print("   task #%s [%s] %s" % (r[0], r[1], " ".join((r[2] or "").split())[:100]))
except Exception as exc:                                       # noqa: BLE001
    print("   tasks: %s" % exc)

print()
print("== did anything about 300DDR / 74114 reach him by any route?")
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for label, needle in (("300DDR", "300DDR"), ("74114", "74114"), ("Fishman", "Fishman")):
    n = m.execute("""select count(*) from messages where direction='outbound'
                     and to_number like '%18483897895%'
                     and instr(lower(coalesce(body,'')), ?) > 0""", (needle.lower(),)).fetchone()[0]
    print("   %-8s reached him %d time(s)" % (label, n))
