#!/usr/bin/env python3
"""Add the VERIFIED implementation plan to items #7/#8, so the shift inherits facts not a hunch.

MEASURED 2026-09-28 20:08Z, everything below is from the schemas and the live rows:

1. THE RESPONDER ALREADY OPENS THE APP DATABASE READ-ONLY, in three places
   (sms-responder.py lines 206, 780, 841: `sqlite3.connect(f"file:{inbox.APP_DB}?mode=ro", uri=True)`),
   and textctx.py:180 does the same with `mode=ro&immutable=0`. So reading `sms_log` is not new
   plumbing - the connection pattern, the path and the read-only discipline all already exist.

2. THE SCHEMA MAPPING IS UNAMBIGUOUS:
       app sms_log            ->  AI-line messages        notes
       twilio_sid             ->  sid                     the dedupe key (app rows may be null)
       direction              ->  direction               'inbound' / 'outbound'
       from_number            ->  from_number
       to_number              ->  to_number
       body                   ->  body
       created_at             ->  date_sent
       status                 ->  status
       (no equivalent)        ->  state                   'new' for anything the responder has not seen
       id                     ->  (fallback dedupe)       use when twilio_sid is null

3. A REAL ROW, so the shape is concrete - and it shows the OTHER HALF ALREADY WORKS BETTER THAN THE
   RESPONDER WOULD:
       id 1024, twilio_sid 'twiml-reply', direction outbound, +17324447361 -> +18483897895,
       body "You're right - most of these don't need replies. The T-Mobile one is the only one that
       might, since they emailed about suspension risk. But since you cancelled and disputed the
       charge, I'll just close that task out and not reply unless you want me to."
   That is a thoughtful, context-aware reply to the owner, written TODAY at 15:59. It was produced by the
   APP's path, not by the responder - `responder.log` still has zero `SENT` lines. So the agent already
   converses with him well; what is missing is that the LEDGER knows about it. That reframes the work:
   the goal is not to make the responder talk to him, it is to make the conversation he already has land
   in the ledger so work gets filed from it.

4. VOLUME: 228 inbound rows from his iPhone all time, 2 in the last 24 hours, newest 2026-09-28T15:58:41.

So the plan is: read `sms_log` as a second inbound source (keeping the AI-line store so nothing already in
it is lost), dedupe on twilio_sid with `id` as the fallback, map as above, and let the already-proven
`_file_owner_request` do the rest.

Usage: python3 add-sms-plan-7-8.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
PLAN = (
    "\n\n=== VERIFIED IMPLEMENTATION PLAN 2026-09-28 20:08Z (facts, not a hunch) ===\n"
    "A. THE RESPONDER ALREADY OPENS THE APP DB READ-ONLY in three places - sms-responder.py lines 206,\n"
    "   780, 841: `sqlite3.connect(f\"file:{inbox.APP_DB}?mode=ro\", uri=True)` - and textctx.py:180 does\n"
    "   the same with `mode=ro&immutable=0`. Reading `sms_log` is therefore NOT new plumbing: the path,\n"
    "   the connection pattern and the read-only discipline all already exist in this codebase.\n"
    "B. SCHEMA MAPPING (unambiguous, from PRAGMA table_info on both stores):\n"
    "     app sms_log.twilio_sid  -> messages.sid          (the dedupe key; app rows may be null)\n"
    "     app sms_log.direction   -> messages.direction\n"
    "     app sms_log.from_number -> messages.from_number\n"
    "     app sms_log.to_number   -> messages.to_number\n"
    "     app sms_log.body        -> messages.body\n"
    "     app sms_log.created_at  -> messages.date_sent\n"
    "     app sms_log.status      -> messages.status\n"
    "     (none)                  -> messages.state        ('new' for anything unseen)\n"
    "     app sms_log.id          -> fallback dedupe when twilio_sid is null\n"
    "C. THE OTHER HALF ALREADY WORKS - AND BETTER THAN THE RESPONDER WOULD. A real row from TODAY:\n"
    "     id 1024, twilio_sid 'twiml-reply', outbound +17324447361 -> +18483897895, body:\n"
    "     \"You're right - most of these don't need replies. The T-Mobile one is the only one that might,\n"
    "      since they emailed about suspension risk. But since you cancelled and disputed the charge,\n"
    "      I'll just close that task out and not reply unless you want me to.\"\n"
    "   That is a thoughtful, context-aware reply to the owner, written by the APP's path at 15:59 today.\n"
    "   `responder.log` still has zero `SENT` lines. SO THE GOAL IS NOT \"make the responder talk to him\"\n"
    "   - it already happens well - it is to make THE CONVERSATION HE ALREADY HAS land in the LEDGER, so\n"
    "   requests in it become work. Reframe the item accordingly before building.\n"
    "D. VOLUME: 228 inbound rows from his iPhone all time; 2 in the last 24 hours; newest\n"
    "   2026-09-28T15:58:41. Small enough that a conservative first cut is safe.\n"
    "E. PROOF REQUIRED: a NEW sms_log row from +18483897895 is picked up on the next responder tick,\n"
    "   becomes a ledger item, and the row id and item id are quoted. Sending a reply is OPTIONAL and\n"
    "   gated on the owner having approved a body - filing the work is the part that must be proven.\n")


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
        if "VERIFIED IMPLEMENTATION PLAN" in (row[0] or ""):
            print("  #%d already carries the plan" % i)
            continue
        if a.apply:
            c.execute("UPDATE work_item SET why=coalesce(why,'')||?, updated_at=? WHERE id=?",
                      (PLAN, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), i))
            print("  #%d plan added" % i)
        else:
            print("  #%d would get the plan" % i)
    if a.apply:
        c.commit()
    c.close()
    print("\n=== the two items ===")
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    for r in c.execute("select id, priority, state, length(why) from work_item where id in (7,8)"):
        print("  #%s p%s %s - %s chars of context for the shift" % (r[0], r[1], r[2], r[3]))
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
