#!/usr/bin/env python3
"""truncation-by-window.py - is the 23% truncated rate a live defect or a September storm?

Round 15 reported 315 of 1,370 delivered texts (23%) would be truncated. The briefings that dominate
it peaked at 290 in September and August has 2, October 1. So the rate has to be reported per window,
or it describes history and gets worked on as if it were current.

Read-only. Uses the live `relay.fit()` for "would be cut".
"""
import sqlite3
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

LIMIT = R.MAX_CHARS
now = datetime.now(timezone.utc)

rows = []
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
for sid, when, body in a.execute("""
    select twilio_sid, created_at, body from sms_log
    where to_number='+18483897895' and direction='outbound'
      and status in ('delivered','sent') and body is not null
"""):
    rows.append((sid, when, body))
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for sid, when, body in m.execute("""
    select sid, coalesce(date_sent_utc, date_sent), body from messages
    where direction='outbound' and to_number like '%18483897895%'
      and coalesce(status,'') in ('delivered','sent') and body is not null
"""):
    rows.append((sid, when, body))


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


seen = set()
per_window = {}
for sid, when, body in rows:
    key = sid or (body or "")[:60]
    if key in seen:
        continue
    seen.add(key)
    at = parse(when)
    if at is None:
        continue
    cut = len(body) > LIMIT and R.fit(body) != body
    for label, days in (("7 days", 7), ("30 days", 30), ("90 days", 90), ("all time", None)):
        if days is not None and at < now - timedelta(days=days):
            continue
        d = per_window.setdefault(label, [0, 0, Counter()])
        d[0] += 1
        if cut:
            d[1] += 1
            head = " ".join((body or "").split())[:28]
            d[2][head] += 1

print("ceiling %d chars - would the gate have to CUT it?" % LIMIT)
print()
for label in ("7 days", "30 days", "90 days", "all time"):
    if label not in per_window:
        print("  %-9s no data" % label)
        continue
    n, cut, shapes = per_window[label]
    print("  %-9s %4d delivered, %4d would be cut  (%5.1f%%)"
          % (label, n, cut, 100.0 * cut / n if n else 0.0))
    for head, c in shapes.most_common(3):
        print("              %3d x %s" % (c, head))
