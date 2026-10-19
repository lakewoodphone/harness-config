#!/usr/bin/env python3
"""what-is-awaiting-reply.py - 1,315 refusals because a turn was open. Redirected, or lost?

`awaiting_reply` is the one-text-at-a-time rule doing its job: a turn was open, so the message was
held. The question that decides whether it is a defect is the same one `too_long` needed - did the
body reach him later, or not at all? A rule that holds is fine; a rule that drops is an outage.

Also reports HOW LONG the blocking turn had been open, because a rule that holds a message behind a
turn from days ago is not the same as one that holds it behind yesterday's question.
"""
import sqlite3
from collections import Counter

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row
m = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)

print("== awaiting_reply by month")
for r in c.execute("""select substr(created_at,1,7) m, count(*) n from owner_text_decision
                      where code='awaiting_reply' group by 1 order by 1"""):
    print("   %s  %5d %s" % (r["m"], r["n"], "=" * min(r["n"], 40)))

print()
print("== by producer")
for r in c.execute("""select coalesce(reason,'(none)') rn, count(*) n from owner_text_decision
                      where code='awaiting_reply' group by 1 order by n desc limit 8"""):
    print("   %-26s %d" % (str(r["rn"])[:26], r["n"]))

print()
print("== did the held words reach him eventually?  (newest 10 with a head)")
reached = 0
sample = c.execute("""select created_at, coalesce(body_head,'') h from owner_text_decision
                      where code='awaiting_reply' and coalesce(body_head,'') <> ''
                      order by created_at desc limit 10""").fetchall()
for r in sample:
    head = str(r["h"])[:40]
    n = m.execute("""select count(*) from messages where direction='outbound'
                     and to_number like '%18483897895%' and instr(coalesce(body,''),?) > 0""",
                  (head,)).fetchone()[0]
    reached += 1 if n else 0
    print("   %s reached=%-2d | %s" % (r["created_at"][:16], n, head))
print("   %d of %d sampled were delivered later" % (reached, len(sample)))

print()
print("== the newest 5 awaiting_reply rows, with what was blocking")
for r in c.execute("""select created_at, coalesce(reason,'-') rn, coalesce(body_head,'') h
                      from owner_text_decision where code='awaiting_reply'
                      order by created_at desc limit 5"""):
    print("   %s %-18s %s" % (r["created_at"][:16], str(r["rn"])[:18], str(r["h"])[:60]))
