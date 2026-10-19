#!/usr/bin/env python3
"""which-reason-cannot-fit.py - the generic sender's over-length bodies, by REASON.

`ai-line` accounts for 259 of the 295 bodies that get cut, but it is one transport carrying many
producers. The AI line's ledger records a `reason` per message, and `sms_log` records the same
distinction differently - so split the over-length bodies by reason and see which producer is really
writing 1,000-character bodies for a 400-character channel.

Also reports, per reason, whether the body LOOKS like a briefing (banned), an answer, or a report -
because the fix differs: a briefing should not exist, an answer should be shorter.
"""
import sqlite3
import sys
from collections import Counter

sys.path.insert(0, "/root/bin")
import owner_text_relay as R  # noqa: E402

LIMIT = R.MAX_CHARS
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

rows = m.execute("""
select sid, coalesce(reason,'(none)'), coalesce(date_sent_utc, date_sent), body
from messages
where direction='outbound' and to_number like '%18483897895%'
  and coalesce(status,'') in ('delivered','sent') and body is not null
""").fetchall()

seen = set()
by_reason = Counter()
longest = {}
examples = {}
for sid, reason, when, body in rows:
    key = sid or (body or "")[:60]
    if key in seen:
        continue
    seen.add(key)
    if len(body) <= LIMIT or R.fit(body) == body:
        continue
    by_reason[reason] += 1
    if len(body) > longest.get(reason, 0):
        longest[reason] = len(body)
        examples[reason] = body

print("ceiling %d chars; over-length bodies in the AI line's ledger: %d"
      % (LIMIT, sum(by_reason.values())))
print()
print("%-30s %5s %8s  %s" % ("reason", "n", "longest", "example"))
print("-" * 116)
for reason, n in by_reason.most_common(12):
    print("%-30s %5d %8d  %s"
          % (str(reason)[:30], n, longest[reason],
             " ".join(str(examples[reason]).split())[:58]))

print()
print("== shape of the longest per reason (first 90 chars)")
for reason, n in by_reason.most_common(8):
    head = " ".join(str(examples[reason]).split())[:90]
    print("  %-26s %s" % (str(reason)[:26], head))
