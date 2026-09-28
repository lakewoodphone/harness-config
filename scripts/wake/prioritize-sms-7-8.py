#!/usr/bin/env python3
"""Make the text-channel items the FIRST thing a shift takes, and give them the best brief available.

WHY PRIORITY AND NOT JUST A BETTER DESCRIPTION. The ledger's order is priority ASC, then oldest. The six
p1 todos are #7, #8, #18, #38, #39, #40 - so a shift takes #7 first already. But #18/#38/#39/#40 are also
p1 and #38/#39/#40 are the thin-project discovery items, which are cheap. The point of this script is
narrower and it is about VALUE: the text channel is the one remaining clause of the owner's objective that
is BUILT AND UNPROVEN, and it is the channel through which everything else reaches him. Items #7 and #8
are two halves of one piece of work, and a shift holding #7 should do #8 in the same shift rather than
close one and let the other wait for the next slot.

So this:
  * sets #7 and #8 to priority 0 - ahead of every other p1, deliberately, so no shift reaches the
    cheap discovery items first and leaves the channel untouched;
  * merges the two into ONE executable instruction by putting the hinge of #8 into #7's definition of
    done, so a shift that takes #7 knows #8 is the same seam;
  * and writes the precise first step: prove the current INPUT IS EMPTY, then extend the source.

It does NOT close anything and does not implement the change.

Usage: python3 prioritize-sms-7-8.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
DOD_ADD = (
    "\n\n=== ADDED 2026-09-28 20:10Z - THE FIRST STEP, AND THE HINGE WITH ITEM #8 ===\n"
    "STEP 0 (do this first, it takes one command and tells you whether you are even in the right place):\n"
    "  run `python3 ~/bin/sms-responder.py run --dry-run` and read the `N to decide` line. Then run\n"
    "  `sqlite3 ~/.sms-inbox/inbox.db \"select max(date_sent) from messages where direction='inbound'\"`\n"
    "  and `sqlite3 ~/personal-secretary-mvp/data/secretary.db \"select max(created_at) from sms_log\n"
    "  where direction='inbound'\"`. If the second is TODAY and the first is months old, you have\n"
    "  confirmed the fault: the responder polls a store his texts never enter. Say so with both\n"
    "  timestamps, and do not spend the shift re-deriving it.\n"
    "STEP 1: extend the responder's inbound source to read `sms_log` READ-ONLY as a second source, using\n"
    "  the schema mapping in the note above and deduping on twilio_sid (falling back to id when null).\n"
    "  Keep the AI-line store as a source so nothing already in it is lost. The connection pattern is\n"
    "  already in this file at lines 206, 780 and 841.\n"
    "STEP 2: prove it on a SOMETHING that cannot harm: copy `inbox.db` to /tmp, point the responder at the\n"
    "  copy, and show the mapping producing a decision. `prove-inbound-path.py` is the template - and note\n"
    "  it closes its own item afterwards, because a proof that leaves items in the ledger is a bug.\n"
    "STEP 3: only then run it live, and quote a REAL new sms_log row from +18483897895 alongside the\n"
    "  ledger item it produced. Sending a reply remains OPTIONAL and needs the owner's approval of a body.\n"
    "THE HINGE WITH #8: filing the work is the half that must be proven here; #8 is the same seam - the\n"
    "  path from a finished shift BACK to his phone. If you have capacity after STEP 3, do #8 in this same\n"
    "  shift rather than leaving it for the next slot, and close both together.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=20)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    for i in (7, 8):
        row = c.execute("SELECT id, priority, state, dod FROM work_item WHERE id=?", (i,)).fetchone()
        if not row:
            print("  #%d not found" % i)
            continue
        print("  #%d now: priority=%s state=%s" % (i, row[1], row[2]))
        if a.apply:
            dod = row[3] or ""
            if "THE FIRST STEP, AND THE HINGE" not in dod:
                dod = dod + DOD_ADD
            c.execute("UPDATE work_item SET priority=0, dod=?, updated_at=? WHERE id=?", (dod, now, i))
    if a.apply:
        c.commit()
    c.close()

    print("\n=== the queue a shift now takes, in order ===")
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    for r in c.execute("select id, project, priority, state, substr(title,1,62) from work_item "
                       "where state='todo' order by priority asc, id asc limit 8"):
        print("  p%s #%-3d %-18s %s" % (r[2], r[0], r[1], r[4]))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
