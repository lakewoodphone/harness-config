#!/usr/bin/env python3
"""producer-body-audit.py - what each producer's sentences actually look like.

The guards decide what may leave; the producers decide what is written. Four producers were fixed
this programme (briefings, digest, CFO questions, reminders). This audits the rest by VOLUME, and
judges each body against one question: is this a sentence a person wrote to a person?

Signals per producer: how many texts, how long, how many open with a receipt ("Got it", "Understood"),
how many are truncated by the gate, how many carry a path or a task id, and one example.

Read-only, both ledgers.
"""
import re
import sqlite3
import sys
from collections import Counter, defaultdict

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

OWNER_LIKE = "%18483897895%"
RECEIPT = re.compile(r"^\s*(got it|understood|noted|ok\b|okay\b|sure\b|will do\b|on it\b|"
                     r"captured as a task|remembered)", re.I)
INTERNAL = re.compile(r"(docs/|lpt-hub/|\.md\b|\.py\b|\bWO\d{8,}\b|\bTask\s*#\d+|branch\s)", re.I)

rows = []
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
for agent, when, body in a.execute("""
    select coalesce(agent_id,'(none)'), created_at, coalesce(body,'') from sms_log
    where to_number='+18483897895' and direction='outbound' and status in ('delivered','sent')
"""):
    rows.append((agent, str(when), body))
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for reason, when, body in m.execute("""
    select coalesce(reason,'('||coalesce(decided_by,'none')||')'),
           coalesce(date_sent_utc, date_sent), coalesce(body,'') from messages
    where direction='outbound' and to_number like ? and coalesce(status,'') in ('delivered','sent')
""", (OWNER_LIKE,)):
    rows.append((str(reason), str(when), body))

seen = set()
by = defaultdict(list)
for agent, when, body in rows:
    key = " ".join(body.split())[:100]
    if not key or key in seen:
        continue
    seen.add(key)
    by[agent].append((when, body))

print("producers of delivered owner text, by volume  (%d distinct texts)" % len(seen))
print()
print("%-30s %5s %6s %7s %7s %8s  %s" % ("producer", "n", "med", "receipt", "internal", "truncated",
                                         "example"))
print("-" * 128)
for agent, items in sorted(by.items(), key=lambda kv: -len(kv[1]))[:12]:
    lens = sorted(len(b) for _w, b in items)
    med = lens[len(lens) // 2]
    receipt = sum(1 for _w, b in items if RECEIPT.match(b))
    internal = sum(1 for _w, b in items if INTERNAL.search(b))
    trunc = sum(1 for _w, b in items if len(b) > R.MAX_CHARS and R.fit(b) != b)
    ex = max(items, key=lambda i: len(i[1]))[1]
    print("%-30s %5d %6d %7d %7d %8d  %s"
          % (agent[:30], len(items), med, receipt, internal, trunc,
             " ".join(ex.split())[:42]))
