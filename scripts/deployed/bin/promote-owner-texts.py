#!/usr/bin/env python3
"""An owner's own text must outrank project work, or the loop is silent by construction.

THE FINDING, measured 2026-09-28 23:01Z. Items filed from the owner's actual texts landed at **priority 3**:

    #52  p3  owner asked by text: "Don't you remember that we were supposed to cancel that service?..."
    #53  p3  owner asked by text: "OK, most of these things are no reply. Are you sure you're even..."
    #76  p3  owner asked by text: "OK, I set a full DSH session today for full automation..."

and the shift picker orders by priority then id, so those sat behind #8 (p0), #54, #65 (p1), then a queue of
p2 project and integration items. His 15:57 text from 15:57Z was still unclaimed at 23:01Z - **seven hours
later** - while the responder's own log said "filed as housekeeping#52" and looked, from the outside, like the
system had responded.

THAT IS HIS COMPLAINT EXACTLY. He said "nothing responded" and he was right: the reply path was broken AND the
item his text produced was buried. Fixing only the first would have left the second - his words would still
change nothing.

WHY p1 AND NOT p0: p0 is reserved for the SMS channel itself (#7 closed, #8 unblocked). An owner request is
the highest-value work that is not the channel, so p1 puts it above every project and integration item while
leaving the channel's own repair at the top.

WHY NOT RUN IT ON A TIMER: this promotes items by their SOURCE, which is a property they already have; it
invents nothing and files nothing. Items from him are identified by source='owner-sms' or the title prefix
'owner asked by text:', which is exactly how the responder tags them.

Usage: python3 promote-owner-texts.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
NOTE = (
    "\n\n=== PROMOTED 2026-09-28 23:02Z - WHY YOUR TEXT OUTRANKS PROJECT WORK ===\n"
    "This item came from the OWNER'S OWN TEXT and was filed at priority 3, behind #8 (p0), #54 and #65 (p1)\n"
    "and a queue of p2 project and integration items - so his 15:57 text was still unclaimed seven hours\n"
    "later while the responder log showed 'filed as housekeeping#52' and looked like a response. He noticed:\n"
    "\"nothing responded\". A reply path that works but leaves his request buried is still silence.\n"
    "Promoted to priority 1: above every project and integration item, below only the SMS channel itself\n"
    "(#8, p0). The definition of done is unchanged - answer his question with evidence and write the answer\n"
    "back here.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=30)
    rows = c.execute(
        "SELECT id, priority, state, substr(title,1,80) FROM work_item "
        "WHERE state IN ('todo','running','blocked') AND (source='owner-sms' OR title LIKE 'owner asked by text:%') "
        "ORDER BY id").fetchall()
    print("owner-text items still open: %d" % len(rows))
    if not rows:
        print("nothing to promote")
        c.close()
        return 0
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for r in rows:
        newp = 1 if (r[1] is None or int(r[1]) > 1) else r[1]
        mark = "" if newp == r[1] else "  -> p1"
        print("  #%-4s p%-2s %-9s %s%s" % (r[0], r[1], r[2], r[3][:54], mark))
        if a.apply and newp != r[1]:
            cur = c.execute("SELECT why FROM work_item WHERE id=?", (r[0],)).fetchone()
            why = (cur[0] or "")
            if "PROMOTED 2026-09-28" not in why:
                why = why + NOTE
            c.execute("UPDATE work_item SET priority=?, why=?, updated_at=? WHERE id=?",
                      (newp, why, now, r[0]))
    if a.apply:
        c.commit()
        print("\n=== the queue a shift now takes, in order ===")
        for r in c.execute("select id, priority, state, substr(title,1,56) from work_item "
                           "where state='todo' order by priority asc, id asc limit 8"):
            print("  p%-2s #%-4s %s" % (r[1], r[0], r[3]))
    else:
        print("\n(dry run: nothing written. use --apply)")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
