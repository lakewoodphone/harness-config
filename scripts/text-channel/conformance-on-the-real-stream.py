#!/usr/bin/env python3
"""conformance-on-the-real-stream.py - the census measured the smaller of two ledgers.

`sms_log` holds 282 of the owner's delivered outbound texts; the AI line's `messages` table holds
1,169, and 887 exist only there - including 40 of the 42 CFO questions. So the conformance census
("11 of 77 refused") was computed on the wrong store and under-represented precisely the class he
complains about most.

This recomputes it on the real stream, with the same rules: rescue first, then the guards, and the
rewritten count reported separately from the refused count. Read-only.
"""
import os
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER = "+18483897895"
DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 14
SINCE = (datetime.now(timezone.utc) - timedelta(days=DAYS)).isoformat()

m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
rows = m.execute("""
select sid, coalesce(date_sent_utc, date_sent) AS sentwhen, body, status
from messages
where direction='outbound' and to_number like '%18483897895%'
  and coalesce(status,'') in ('delivered','sent')
  and coalesce(date_sent_utc, date_sent) >= ?
order by 2
""", (SINCE,)).fetchall()

print("window: last %d days (since %s)" % (DAYS, SINCE[:19]))
print("delivered outbound texts to the owner, from the AI line's ledger: %d" % len(rows))
print()

seen = set()
delivered = 0
refused = []
rewritten = 0
by_class = Counter()
for sid, when, body, status in rows:
    key = sid or ("b", (body or "")[:80])
    if key in seen:
        continue
    seen.add(key)
    delivered += 1
    out, note = R._rescue_reminder(body or "", OWNER, "cron")
    if note and "rewritten" in str(note):
        rewritten += 1
    why = R.internal_prose(out) or R.credential_request(out)
    if why:
        code = str(why).split(" \u2014 ")[0]
        by_class[code] += 1
        refused.append((when, code, " ".join((body or "").split())[:100]))

print("CONFORMANCE on the real stream")
print("  %d delivered, %d would be REFUSED (%.1f%%), %d would be REWRITTEN and sent"
      % (delivered, len(refused),
         (100.0 * len(refused) / delivered) if delivered else 0.0, rewritten))
print()
print("  by class:")
for k, v in by_class.most_common():
    print("    %-24s %d" % (k, v))
print()
print("  every refused text, newest first:")
for when, code, body in sorted(refused, key=lambda r: str(r[0]), reverse=True)[:14]:
    print("    %s %-22s %s" % (str(when)[:16], code, body))

