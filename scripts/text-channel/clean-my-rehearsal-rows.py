#!/usr/bin/env python3
"""clean-my-rehearsal-rows.py - remove the topic rows MY test created, and nothing else.

CAUSE. `owner_text_relay._topic()` loads `owner_topic.py`, which keeps its own store at
`OWNER_TOPIC_DB` (default `/root/.owner-text/relay.db`) -- a DIFFERENT env var from the relay's
`OWNER_TEXT_RELAY_DB`. My gate rehearsal redirected only the relay store, so its three SEND cases
wrote real topic rows into the production ledger at 17:27:43. Those rows would suppress genuine
messages for the topic cooldown window (20 hours).

SCOPE. Only rows whose `first_at` is at or after 17:25:00Z AND whose `last_body` is one of the
three exact bodies the rehearsal submitted. Every removed row is printed first. Nothing else is
touched; nothing is deleted that this session did not create.

Dry-run by default.
"""
import sqlite3
import sys

DB = "/root/.owner-text/relay.db"
CUT = "2026-10-19T17:25:00+00:00"
BODIES = (
    "Task #12 is still open in the hub.",
    "URGENT - CEO needs a decision Task #1342: Was the macOS Chrome sign-in to "
    "lakewoodphoneandtech@gmail.com legitimate (your device), or is this unauthorized access? "
    "Reply to this text and I'll get it.",
    "The Q3 ST-50 is filed. Confirmation number 4471. Nothing needed from you.",
)

c = sqlite3.connect(DB)
c.row_factory = sqlite3.Row
rows = [dict(r) for r in c.execute("select * from owner_topic where first_at >= ?", (CUT,))]
mine = [r for r in rows if str(r.get("last_body") or "") in BODIES]

print("rows in the topic ledger created since %s: %d" % (CUT, len(rows)))
print("of those, created by MY rehearsal: %d" % len(mine))
print()
if not mine:
    print("nothing to clean")
else:
    for r in mine:
        print("  REMOVE  topic=%-46s sends=%s refused=%s first_at=%s"
              % (str(r["topic"])[:46], r["sends"], r["refused"], r["first_at"]))
    print()
    for r in rows:
        if r not in mine:
            print("  KEEP    topic=%-46s first_at=%s (not mine - left alone)"
                  % (str(r["topic"])[:46], r["first_at"]))
    if "--apply" in sys.argv:
        n = 0
        for r in mine:
            cur = c.execute("delete from owner_topic where topic = ? and first_at = ?", (r["topic"], r["first_at"]))
            n += cur.rowcount
        c.commit()
        print()
        print("APPLIED: deleted %d row(s)" % n)
    else:
        print()
        print("DRY RUN - re-run with --apply")
c.close()

