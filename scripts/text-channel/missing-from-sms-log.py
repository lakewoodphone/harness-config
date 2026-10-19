#!/usr/bin/env python3
"""missing-from-sms-log.py - how much of the owner channel is only in the AI line's ledger?

Two durable records exist and both are legitimate:
  * `authority.db: sms_log`      - every send through the APP's choke point
  * `~/.sms-inbox/inbox.db: messages` - every send through the AI LINE (`textsend`)

The replay, the conformance census and every "N texts reached him" figure so far read `sms_log`
only. This counts, on the OWNER's number, how many delivered outbound texts exist in `messages` and
not in `sms_log` - per month, so the size and the recency of the gap are both visible.
"""
import sqlite3
from collections import Counter

OWNER = "+18483897895"
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

log_sids = {r[0] for r in a.execute(
    "select twilio_sid from sms_log where twilio_sid is not null and twilio_sid <> ''")}
log_sids.discard("twiml-reply")

rows = m.execute("""
select sid, status, coalesce(date_sent_utc, date_sent), body
from messages
where direction='outbound' and to_number like '%18483897895%'
  and coalesce(status,'') in ('delivered','sent')
""").fetchall()

only_line = [r for r in rows if (r[0] or "") not in log_sids]
asks = [r for r in only_line if "CFO [ask-" in (r[3] or "")]

print("outbound delivered to the owner in the AI line's ledger : %d" % len(rows))
print("  of those, ALSO in sms_log (by sid)                    : %d" % (len(rows) - len(only_line)))
print("  ONLY in the AI line's ledger                          : %d" % len(only_line))
print("    of which carry a CFO ask                            : %d" % len(asks))
print()
by_month = Counter(str(r[2] or "")[:7] for r in only_line)
print("== the ones sms_log does not hold, by month")
for k in sorted(by_month):
    print("   %-8s %3d %s" % (k, by_month[k], "=" * min(by_month[k], 40)))
print()
by_month_asks = Counter(str(r[2] or "")[:7] for r in asks)
print("== the CFO asks among them, by month")
for k in sorted(by_month_asks):
    print("   %-8s %d" % (k, by_month_asks[k]))
print()
newest = sorted((str(r[2] or ""), r[3]) for r in only_line if r[2])[-3:]
print("== newest three that only the AI line recorded")
for when, body in newest:
    print("   %s | %s" % (when[:19], " ".join((body or "").split())[:80]))
