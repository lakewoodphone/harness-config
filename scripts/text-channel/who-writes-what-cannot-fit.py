#!/usr/bin/env python3
"""who-writes-what-cannot-fit.py - 23% of everything sent was cut to fit. Whose bodies are they?

The replay says 315 of 1,370 delivered texts had to be truncated. A gate cannot fix that - the
composer wrote a body longer than one text and the gate cut it. So: group the over-length bodies by
PRODUCER and show the biggest offenders, with how far over they are and the shape of the cut.

Read-only. Uses the live `relay.fit()` so "would be cut" means exactly what the gate would do.
"""
import os
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER_LIKE = "%18483897895%"
LIMIT = R.MAX_CHARS
print("the relay's ceiling: %d chars" % LIMIT)
print()

rows = []

# the app's ledger
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
for sid, agent, when, body in a.execute("""
    select twilio_sid, coalesce(agent_id,'-'), created_at, body from sms_log
    where to_number='+18483897895' and direction='outbound'
      and status in ('delivered','sent') and body is not null
"""):
    rows.append((sid or ("b", (body or "")[:60]), agent, when, body))

# the AI line's ledger
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for sid, when, body in m.execute("""
    select sid, coalesce(date_sent_utc, date_sent), body from messages
    where direction='outbound' and to_number like ?
      and coalesce(status,'') in ('delivered','sent') and body is not null
""", (OWNER_LIKE,)):
    rows.append((sid or ("b", (body or "")[:60]), "ai-line", when, body))

seen = set()
by_producer = defaultdict(list)
total = 0
for key, agent, when, body in rows:
    if key in seen:
        continue
    seen.add(key)
    total += 1
    if len(body) <= LIMIT:
        continue
    cut = R.fit(body)
    if cut == body:
        continue
    by_producer[str(agent)].append((len(body), len(cut), when, body))

print("distinct delivered texts: %d" % total)
cut_total = sum(len(v) for v in by_producer.values())
print("would be CUT to fit        : %d (%.1f%%)" % (cut_total, 100.0 * cut_total / total if total else 0))
print()
print("%-18s %6s %8s %8s  %s" % ("producer", "n", "median", "worst", "example"))
print("-" * 118)
for agent, items in sorted(by_producer.items(), key=lambda kv: -len(kv[1])):
    lens = sorted(i[0] for i in items)
    median = lens[len(lens) // 2]
    worst = lens[-1]
    ex = max(items, key=lambda i: i[0])[3]
    print("%-18s %6d %8d %8d  %s"
          % (agent[:18], len(items), median, worst, " ".join(ex.split())[:60]))

print()
print("== the ten longest bodies, whatever their producer")
allcuts = [(i[0], agent, i[3]) for agent, items in by_producer.items() for i in items]
for n, agent, body in sorted(allcuts, reverse=True)[:10]:
    print("  %5d chars  %-14s %s" % (n, agent[:14], " ".join(body.split())[:80]))

print()
print("== how far over the ceiling they run")
over = Counter((n // 100) * 100 for n, _a, _b in allcuts)
for k in sorted(over):
    print("   %4d-%4d chars : %d" % (k, k + 99, over[k]))
