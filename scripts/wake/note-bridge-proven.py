#!/usr/bin/env python3
"""Record on item #7 that the inbound half is now BUILT AND VERIFIED, and say precisely what is left.

This does NOT close #7. What it does is stop a future shift re-doing verified work, and name the remaining
unknown precisely - because "the text channel does not work" and "the text channel works for everything
except a real text from him" are very different starting points.

Usage: python3 note-bridge-proven.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
NOTE = (
    "\n\n=== INBOUND HALF BUILT AND VERIFIED 2026-09-28 20:30Z ===\n"
    "The fault was that the owner's texts arrive in the app's `sms_log` while the responder read\n"
    "`~/.sms-inbox/inbox.db`, whose newest inbound row was 2026-04-29. That is now BRIDGED:\n"
    "  * `~/bin/mirror-owner-sms.py` copies inbound rows from the app store into the inbox store. It reads\n"
    "    the app database READ-ONLY (`mode=ro`), takes only inbound rows, maps the schema explicitly\n"
    "    (twilio_sid->sid, created_at->date_sent, ...), DEDUPES on sid, and is INSERT-ONLY - it never\n"
    "    updates a row and never writes to the app database.\n"
    "  * SCHEDULED: `*/5 * * * *` in the crontab, with the measurement written into the cron comment.\n"
    "  * A RECENCY WINDOW OF 7 DAYS IS DELIBERATE: an unbounded first run would have mirrored 27 rows from\n"
    "    as far back as 2026-03-23, including several 'Public ingress probe' test messages, and every one\n"
    "    would have become a ledger item. The responder decides about new texts, not history.\n"
    "  * WHY A MIRROR AND NOT A CHANGE TO THE RESPONDER: the responder runs LIVE every five minutes with\n"
    "    `--send`, so editing its worklist would put new code in the path that texts a human. A separate\n"
    "    process means the responder keeps its proven path; if the mirror is wrong the worst case is that\n"
    "    no new rows appear. Containment first - the responder is untouched.\n"
    "\n"
    "PROVEN, end to end, on copies with production only ever READ (`~/bin/prove-owner-sms-bridge.sh`):\n"
    "  a NEW inbound row in an app-database copy -> the REAL mirror reports 'to insert 1' and\n"
    "  'inserted 1 row(s)' -> the row is present in the inbox copy in the responder's schema with\n"
    "  state='new' and sid `SM_leanproof_*` -> and the DECISIVE CHECK: the responder's OWN `worklist()`\n"
    "  called over that copy RETURNS IT. A second run inserts nothing (idempotent). Production verified\n"
    "  afterwards: 0 proof rows in the app, 0 awaiting in the live inbox, app sms_log still 982 rows.\n"
    "\n"
    "ALSO WORTH KNOWING BEFORE COPYING THAT DATABASE: `/tmp` is a tmpfs with a 12 GB limit and the app\n"
    "database IS 12 GB, so a copy into /tmp fails with `disk I/O error` - which looks like a code bug and\n"
    "is capacity. In /home/zabz a full `VACUUM INTO` of it runs for minutes (the first attempt wrote\n"
    "9.9 GB before being killed). Copy only `sms_log` when that is all you need.\n"
    "\n"
    "WHAT REMAINS ON THIS ITEM: only that no REAL future text from him has flowed through, because that\n"
    "needs him to text. The next message he sends is the end-to-end proof, and `~/.sms-inbox/mirror.log`\n"
    "plus `~/bin/sms-responder.py run --dry-run` are where to look for it. Do NOT rebuild the bridge.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=20)
    row = c.execute("SELECT why FROM work_item WHERE id=7").fetchone()
    if not row:
        print("  #7 not found")
        return 1
    if "INBOUND HALF BUILT AND VERIFIED" in (row[0] or ""):
        print("  #7 already carries the note")
    elif a.apply:
        c.execute("UPDATE work_item SET why=coalesce(why,'')||?, updated_at=? WHERE id=7",
                  (NOTE, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")))
        c.commit()
        print("  #7 updated")
    else:
        print("  #7 would be updated (dry run)")
    c.close()
    print("\n=== #7 and #8 now ===")
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    for r in c.execute("select id, priority, state, length(why) from work_item where id in (7,8)"):
        print("  #%s p%s %s - %s chars of context" % (r[0], r[1], r[2], r[3]))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
