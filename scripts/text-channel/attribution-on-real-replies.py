#!/usr/bin/env python3
"""attribution-on-real-replies.py - is_non_answer over his actual texts, not test fixtures.

Objective item 4 is "correct reply attribution", and so far it is proven by 21 unit cases and one
driven call. This runs the deployed classifier over every inbound text of his in both ledgers and
reports what it says, with examples - the only way to know whether the rules match how he actually
writes.

The interesting number is NOT "how many are non-answers". It is: of the texts it calls non-answers,
how many were him genuinely telling the CFO it had asked something stupid - and of the texts it
clears, how many are answers a filer could use.
"""
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, "/root/bin")
import textdecide as T  # noqa: E402

OWNER = "%18483897895%"
rows = []
a = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
for when, body in a.execute("""
    select created_at, coalesce(body,'') from sms_log
    where from_number='+18483897895' and direction='inbound'
"""):
    rows.append((str(when), body))
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for when, body in m.execute("""
    select coalesce(date_sent_utc, date_sent), coalesce(body,'') from messages
    where direction='inbound' and from_number like ?
""", (OWNER,)):
    rows.append((str(when), body))

seen = set()
texts = []
for when, body in rows:
    key = " ".join((body or "").split())[:120]
    if not key or key in seen:
        continue
    seen.add(key)
    texts.append((when, body))

print("distinct inbound texts of his: %d" % len(texts))
print()

flagged = []
cleared = []
for when, body in texts:
    hit, why = T.is_non_answer(body)
    (flagged if hit else cleared).append((when, body, why))

print("called a NON-ANSWER : %d (%.1f%%)" % (len(flagged), 100.0 * len(flagged) / len(texts)))
print("called an answer    : %d (%.1f%%)" % (len(cleared), 100.0 * len(cleared) / len(texts)))
print()

print("== the cues that fired, most common first")
cues = Counter()
for _w, _b, why in flagged:
    cue = str(why).split("(")[-1].split(")")[0] if "(" in str(why) else str(why)[:40]
    cues[cue] += 1
for cue, n in cues.most_common(10):
    print("   %-46s %d" % (cue[:46], n))

print()
print("== 10 non-answers, newest first (are these really non-answers?)")
for when, body, why in sorted(flagged, key=lambda r: r[0], reverse=True)[:10]:
    print("   %s | %s" % (when[:10], " ".join(body.split())[:88]))

print()
print("== 8 it CLEARED - if any of these is a complaint, the rule under-fires")
for when, body, why in sorted(cleared, key=lambda r: r[0], reverse=True)[:8]:
    print("   %s | %s" % (when[:10], " ".join(body.split())[:88]))
