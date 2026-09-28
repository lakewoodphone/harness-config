#!/usr/bin/env python3
"""THE TEXT CHANNEL'S REAL FAULT: the responder reads a store his texts never enter.

MEASURED 2026-09-28 20:07Z, and it corrects what I told the last shift in the notes on items #7/#8 - the
gap is NOT a missing Dialpad bridge.

WHAT IS ACTUALLY TRUE:
  * The OWNER'S TEXTS ARE ARRIVING. The app's own `sms_log` - written by the Twilio webhook in
    personal-secretary-mvp/app/main.py - holds **982 rows**, 228 of them from his iPhone, and the newest
    are **today**:
        2026-09-28T15:59:00  outbound  +17324447361 -> +18483897895
        2026-09-28T15:58:41  inbound   +18483897895 -> +17324447361
  * The RESPONDER reads a DIFFERENT store: `~/.sms-inbox/inbox.db`, whose newest INBOUND row is
    **2026-04-29** and whose newest outbound is **2026-07-29**. So the responder has been polling a store
    that stopped receiving traffic months ago, which is why every tick says `0 to decide`.
  * The Dialpad tables are NOT the channel for an ordinary text to his iPhone - only 5 rows ever, newest
    2025-11-05. The Dialpad line is the SHOP's business line (`7324447361`, newest 2026-09-20). So the
    "bridge Dialpad to the responder" framing in my previous note was wrong, and saying so precisely
    matters: a shift chasing that bridge would do a day's work on the wrong seam.
  * OUTBOUND to his iPhone ALREADY WORKS on that line - the most recent rows are an evening briefing and
    an "URGENT EMAIL" alert to +18483897895 on 2026-09-23. Those come from the app's own notify path
    (POST /tools/notify-owner), not from the responder.

SO THE FIX IS A SOURCE CHANGE, NOT A NEW BRIDGE: the responder must read the app's `sms_log` (read-only -
it already reads the app DB read-only elsewhere) as well as, or instead of, the AI-line store, and treat
the webhook's row as the inbound text. Everything downstream of that already works and is proven:
`_file_owner_request` routes it to the right project, and the send gate to his iPhone is OPEN.

This appends the measurement to items #7 and #8, supersedes the wrong note, and says plainly which
sentence of the old note to ignore.

Usage: python3 fix-sms-diagnosis.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
NOTE = (
    "\n\n=== CORRECTED DIAGNOSIS 2026-09-28 20:07Z - READ THIS, IT SUPERSEDES THE NOTE ABOVE ===\n"
    "IGNORE the sentence in the earlier note that says the remaining work is bridging DIALPAD to the\n"
    "responder. That framing is WRONG, and I verified it: the Dialpad tables hold only 5 rows for his\n"
    "iPhone number ever (newest 2025-11-05) because Dialpad is the SHOP's business line. A text from him\n"
    "to the AI line does not go anywhere near Dialpad.\n"
    "\n"
    "WHAT IS ACTUALLY TRUE, measured:\n"
    "  * HIS TEXTS ARE ARRIVING. The app's own `sms_log` (written by the Twilio webhook in\n"
    "    personal-secretary-mvp/app/main.py) holds 982 rows, 228 from his iPhone, and the newest are\n"
    "    TODAY:\n"
    "        2026-09-28T15:59:00  outbound  +17324447361 -> +18483897895\n"
    "        2026-09-28T15:58:41  inbound   +18483897895 -> +17324447361\n"
    "  * THE RESPONDER READS A DIFFERENT STORE. `~/.sms-inbox/inbox.db` has NO inbound row newer than\n"
    "    2026-04-29 and no outbound newer than 2026-07-29. The responder has been polling a store that\n"
    "    stopped receiving traffic months ago - which is exactly why every tick prints `0 to decide`.\n"
    "  * OUTBOUND TO HIS IPHONE ALREADY WORKS on that line: the newest rows are an evening briefing and an\n"
    "    URGENT EMAIL alert to +18483897895 on 2026-09-23, sent by the app's notify path\n"
    "    (POST /tools/notify-owner), not by the responder.\n"
    "\n"
    "SO THE WORK IS A SOURCE CHANGE, NOT A NEW BRIDGE:\n"
    "  1. read the app's `sms_log` READ-ONLY (the responder already opens the app DB read-only elsewhere)\n"
    "     and treat its inbound rows as the texts to decide on - keeping the AI-line store as a second\n"
    "     source so nothing already in it is lost;\n"
    "  2. keep `sid` as the dedupe key so a row seen in both stores is handled once;\n"
    "  3. everything downstream is ALREADY built and proven: `_file_owner_request` routes an owner text to\n"
    "     the right project and files a ledger item, and the send gate to his iPhone reports OPEN.\n"
    "  The proof for this item is therefore: a NEW row in sms_log from +18483897895 is picked up by the\n"
    "  responder on its next tick, becomes a ledger item, and (only if he has approved a body) gets a\n"
    "  reply - with the row id and the item id quoted.\n"
    "\n"
    "THE GENERAL LESSON, worth more than the fix: I read `0 to decide` on every tick for hours as evidence\n"
    "that the responder was broken. It was evidence that its INPUT WAS EMPTY. A reading that cannot\n"
    "distinguish \"nothing to do\" from \"I am looking in the wrong place\" is not a reading.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=20)
    for i in (7, 8):
        row = c.execute("SELECT why FROM work_item WHERE id=?", (i,)).fetchone()
        if not row:
            print("  #%d not found" % i)
            continue
        if "CORRECTED DIAGNOSIS" in (row[0] or ""):
            print("  #%d already carries the corrected diagnosis" % i)
            continue
        if a.apply:
            c.execute("UPDATE work_item SET why=coalesce(why,'')||?, updated_at=? WHERE id=?",
                      (NOTE, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), i))
            print("  #%d corrected" % i)
        else:
            print("  #%d would be corrected" % i)
    if a.apply:
        c.commit()
    c.close()

    print("\n=== the two items now ===")
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    for r in c.execute("select id, priority, state, length(why) as why_len from work_item where id in (7,8)"):
        print("  #%s p%s %s (%s chars of context)" % (r[0], r[1], r[2], r[3]))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
