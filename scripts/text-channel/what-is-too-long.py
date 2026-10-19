#!/usr/bin/env python3
"""what-is-too-long.py - 1,273 refusals because the body did not fit; did any of them go out?

`too_long` is the second-largest refusal class in owner_text_decision after gate_error. Unlike a
truncation, a `too_long` verdict is a REFUSAL - the text was never sent. So the questions are:

  * when did they happen, and are they still happening?
  * which producers write bodies that cannot fit, and how long are they?
  * for a sample, did the same words reach him later (a retry that fitted), or not at all?

The last question is the one that decides whether 1,273 is a redirection or 1,273 losses.
"""
import sqlite3
from collections import Counter

c = sqlite3.connect("file:/root/authority.db?mode=ro", uri=True)
c.row_factory = sqlite3.Row

print("== too_long by month")
for r in c.execute("""select substr(created_at,1,7) m, count(*) n from owner_text_decision
                      where code='too_long' group by 1 order by 1"""):
    print("   %s  %5d %s" % (r["m"], r["n"], "=" * min(r["n"], 40)))

print()
print("== too_long by reason (the producer)")
for r in c.execute("""select coalesce(reason,'(none)') rn, count(*) n,
                             cast(avg(chars) as int) avgc, max(chars) maxc
                      from owner_text_decision where code='too_long'
                      group by 1 order by n desc limit 10"""):
    print("   %-24s n=%-5d avg=%-5d max=%d" % (str(r["rn"])[:24], r["n"], r["avgc"] or 0,
                                               r["maxc"] or 0))

print()
print("== the heaviest heads")
for r in c.execute("""select body_head, chars, count(*) n from owner_text_decision
                      where code='too_long' group by 1 order by n desc limit 6"""):
    print("   %-52s chars=%-5s n=%d" % (str(r["body_head"])[:52], r["chars"], r["n"]))

print()
print("== did those words reach him later? sample the newest 8 that have a head")
sent = sqlite3.connect("file:/root/.sms-inbox/inbox.db?mode=ro", uri=True)
for r in c.execute("""select created_at, chars, coalesce(body_head,'') h from owner_text_decision
                      where code='too_long' and coalesce(body_head,'') <> ''
                      order by created_at desc limit 8"""):
    head = str(r["h"])[:40]
    try:
        hit = sent.execute("""select count(*) from messages where direction='outbound'
                              and to_number like '%18483897895%' and instr(coalesce(body,''),?)
                              > 0""", (head,)).fetchone()[0]
    except Exception:                                          # noqa: BLE001
        hit = "?"
    print("   %s chars=%-5s reached=%s | %s" % (r["created_at"][:16], r["chars"], hit, head))
