#!/usr/bin/env python3
"""since-deploy.py - what has actually happened since the guards went live at 17:02Z?

Every guard so far is proved by direct call and by replay. The one thing nobody has seen is a
real message going through submit() with the new rules in the path. This prints exactly that:
every attempt since the deploy, its verdict, its reason, and every text that reached him.
"""
import sqlite3
from datetime import datetime, timezone

DEPLOY = "2026-10-19T17:02:00+00:00"

r = sqlite3.connect("file:/root/.owner-text/relay.db?mode=ro", uri=True)
r.row_factory = sqlite3.Row
print("== relay attempts since the guards went live (%s)" % DEPLOY)
rows = r.execute("""
select attempt_id, at, door, subsystem, verdict, verdict_reason, urgency, class_hint,
       substr(replace(body,char(10),' '),1,70) b
from attempt where at >= ? order by attempt_id
""", (DEPLOY,)).fetchall()
if not rows:
    print("   NONE. No text has passed submit() since the deploy.")
for x in rows:
    print("   %s %-12s %-20s %-9s %-22s u=%-7s h=%-6s | %s"
          % (x["at"][11:19], x["door"], str(x["subsystem"])[:20], x["verdict"],
             str(x["verdict_reason"])[:22], x["urgency"], str(x["class_hint"]),
             x["b"] or ""))

print()
print("== texts that actually reached him since the deploy")
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
n = 0
for x in a.execute("""
select created_at, agent_id, status, substr(replace(body,char(10),' '),1,80)
from sms_log
where to_number='+18483897895' and direction='outbound' and created_at >= ?
order by created_at""", (DEPLOY,)):
    n += 1
    print("   %s %-20s %-10s | %s" % (x[0][11:19], str(x[1])[:20], x[2], x[3] or ""))
if n == 0:
    print("   NONE.")

print()
print("== inbound from him since the deploy (does the awake marker see it?)")
m = 0
for x in a.execute("""
select created_at, substr(replace(body,char(10),' '),1,70) from sms_log
where from_number='+18483897895' and direction='inbound' and created_at >= ?
order by created_at""", (DEPLOY,)):
    m += 1
    print("   %s | %s" % (x[0][11:19], x[1] or ""))
if m == 0:
    print("   none")
print()
print("== inbound marker rows in the relay store (written by record_inbound)")
try:
    q = r.execute("select count(*) from attempt where verdict='INBOUND'").fetchone()[0]
    newest = r.execute("select max(at) from attempt where verdict='INBOUND'").fetchone()[0]
    print("   %d row(s); newest %s" % (q, newest))
except Exception as exc:                                       # noqa: BLE001
    print("   %s" % exc)
r.close()
