#!/usr/bin/env python3
"""would-a-cap-help.py - how much of the crowd would a "hold after N" rule have prevented?

Measured: 271 of 298 replies followed MORE THAN ONE text, median 9, maximum 76. That is the
"unified brain is not working" complaint at true scale. Before adding a rule, measure what the rule
would buy.

METHOD. Walk the merged owner channel in time order. Each outbound text is "unanswered since his last
reply" if no inbound from him sits between it and the previous one. Count, per reply, how many texts
had accumulated. Then, for a candidate cap N, count the texts that a "hold everything after N
unanswered" rule would have withheld.

A withheld text is not deleted: the senders are periodic, so it comes back later. So the cost is
delay, and the benefit is a shorter queue in front of his reply.
"""
import sqlite3
import sys
from collections import Counter

OWNER = "%18483897895%"[1:]
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

events = []
for sid, when, body in a.execute("""
    select coalesce(twilio_sid, 'a'||id), created_at, coalesce(body,'') from sms_log
    where (to_number='+18483897895' or from_number='+18483897895') and body is not null
"""):
    events.append((str(when), "out" if True else "in", sid, body))
# direction is not carried above; redo properly
events = []
for sid, direction, when, body in a.execute("""
    select coalesce(twilio_sid, 'a'||id), direction, created_at, coalesce(body,'')
    from sms_log where to_number='+18483897895' or from_number='+18483897895'
"""):
    if direction in ("outbound", "inbound"):
        events.append((str(when), "out" if direction == "outbound" else "in", sid, body))
for sid, when, body in m.execute("""
    select sid, coalesce(date_sent_utc, date_sent), coalesce(body,'') from messages
    where direction='outbound' and to_number like ? and coalesce(status,'') in ('delivered','sent')
""", (OWNER,)):
    events.append((str(when), "out", sid, body))
for sid, when, body in m.execute("""
    select sid, coalesce(date_sent_utc, date_sent), coalesce(body,'') from messages
    where direction='inbound' and from_number like ?
""", (OWNER,)):
    events.append((str(when), "in", sid, body))

from datetime import datetime, timezone


def parse(v):
    t = str(v or "").strip()
    if not t:
        return None
    try:
        return datetime.fromisoformat(t.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        pass
    try:
        from email.utils import parsedate_to_datetime
        g = parsedate_to_datetime(t)
        return (g if g.tzinfo else g.replace(tzinfo=timezone.utc)).astimezone(timezone.utc)
    except Exception:                                          # noqa: BLE001
        return None


timed = [(parse(w), kind, sid, body) for w, kind, sid, body in events]
timed = [t for t in timed if t[0] is not None]
timed.sort(key=lambda t: t[0])
print("merged owner channel events with a readable timestamp: %d" % len(timed))

# walk it
running = 0
replies = []          # texts accumulated before each of his replies
out_total = 0
per_cap = {2: 0, 3: 0, 5: 0}
for when, kind, sid, body in timed:
    if kind == "out":
        out_total += 1
        running += 1
        for cap in per_cap:
            if running > cap:
                per_cap[cap] += 1
    else:
        if running:
            replies.append(running)
        running = 0

print("outbound texts                    : %d" % out_total)
print("his replies arriving after a burst : %d" % len(replies))
if replies:
    replies.sort()
    print("  median %d, p90 %d, max %d"
          % (replies[len(replies) // 2], replies[int(len(replies) * 0.9)], replies[-1]))
print()
print("withheld by a 'hold after N unanswered' rule (they come back later, not lost):")
for cap in sorted(per_cap):
    print("  N=%-2d  %5d texts withheld  (%.1f%% of all outbound)"
          % (cap, per_cap[cap], 100.0 * per_cap[cap] / out_total if out_total else 0))
