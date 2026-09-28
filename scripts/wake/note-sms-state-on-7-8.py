#!/usr/bin/env python3
"""Put the measured state of the text channel onto items #7 and #8, so the next shift starts informed.

WHAT WAS MEASURED, 2026-09-28 20:03Z - three facts that change the shape of that work:

1. THE OWNER-TEXT-TO-LEDGER PATH WORKS AND IS PROVEN. `prove-inbound-path.py` inserts a synthetic text
   from his number on a THROWAWAY copy of the store and drives the REAL responder worklist: it routes to
   the right project and files a ledger item, and sends nothing. (The proof used to leave its own item
   behind; it now closes it as `dropped` before returning, because a proof that pollutes the backlog it
   verifies manufactures the duplicate work this system exists to prevent.)

2. THE SEND PATH TO HIS PHONE DEMONSTRABLY WORKS - JUST NOT FROM THE RESPONDER. The store holds 992
   outbound rows to +17325691594 (his Google Voice) and **531 to +18483897895 (his personal iPhone)**,
   while `responder.log` has ZERO `SENT` lines. So something in this system HAS successfully texted his
   iPhone 531 times; the responder is not that thing. The question for item #7 is therefore not "can we
   send" but "why has the responder never sent", and the 531 rows are the evidence that the transport,
   credentials and gate all function.

3. THEREFORE THE REMAINING WORK IS WIRING, NOT TRANSPORT. His live texts arrive on the Dialpad line and
   land in the Dialpad tables; the responder reads `~/.sms-inbox/inbox.db`, the Twilio-era store. If
   those two are not bridged, a text from him cannot reach the responder at all, and the responder's "0
   to decide" on every tick is the correct reading of an EMPTY input rather than of a broken responder.

This appends all three to both items. It does not close them: the wiring is real work and nobody has done
it.

Usage: python3 note-sms-state-on-7-8.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
NOTE = (
    "\n\n=== MEASURED STATE OF THE TEXT CHANNEL, 2026-09-28 20:03Z - START FROM HERE ===\n"
    "1. THE OWNER-TEXT-TO-LEDGER PATH WORKS AND IS PROVEN. `prove-inbound-path.py` inserts a synthetic\n"
    "   text from his number into a THROWAWAY copy of the store and drives the REAL responder worklist:\n"
    "   it routes to the right project and files a ledger item, and sends nothing. Re-run it to see the\n"
    "   proof; it now cleans up its own item as `dropped` (it used to leave duplicates behind).\n"
    "2. THE SEND PATH TO HIS PHONE WORKS, but NOT from the responder. The store holds 992 outbound rows\n"
    "   to +17325691594 (Google Voice) and **531 to +18483897895 (his personal iPhone)**, while\n"
    "   `responder.log` has ZERO `SENT` lines. Something here has texted his iPhone 531 times; the\n"
    "   responder is not that thing. So the question is NOT \"can we send\" - the transport, the\n"
    "   credentials and the gate all demonstrably function - it is \"why has the responder never sent\".\n"
    "3. THE REMAINING WORK IS WIRING, NOT TRANSPORT. His live texts arrive on the DIALPAD line and land\n"
    "   in the Dialpad tables; the responder reads `~/.sms-inbox/inbox.db`, the Twilio-era store. If the\n"
    "   two are not bridged then a text from him cannot reach the responder at all, and its \"0 to\n"
    "   decide\" on every tick is the correct reading of an EMPTY INPUT, not of a broken responder.\n"
    "   SO: first establish whether ANY inbound message from +18483897895 can reach the responder's\n"
    "   worklist today. If it cannot, that bridge is the whole of item #7 and everything else is moot.\n"
    "4. GATES VERIFIED LIVE: +18483897895 is `relationship=owner, allow=auto` and the send gate reports\n"
    "   `OPEN - recipient is the owner's own number`; +17325691594 is `owner-google-voice, allow=never`\n"
    "   (monitor only, never a destination). Third-party sends are closed by default.\n")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    c = sqlite3.connect(DB, timeout=20)
    for i in (7, 8):
        row = c.execute("SELECT id, state, why FROM work_item WHERE id=?", (i,)).fetchone()
        if not row:
            print("  #%d not found" % i)
            continue
        if "MEASURED STATE OF THE TEXT CHANNEL" in (row[2] or ""):
            print("  #%d already carries the note" % i)
            continue
        if a.apply:
            c.execute("UPDATE work_item SET why=coalesce(why,'')||?, updated_at=? WHERE id=?",
                      (NOTE, datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), i))
            print("  #%d updated" % i)
        else:
            print("  #%d would be updated" % i)
    if a.apply:
        c.commit()
    c.close()

    print("\n=== the ledger after the proof hygiene ===")
    c = sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=20)
    for r in c.execute("select state, count(*) from work_item group by 1 order by 2 desc"):
        print("  %-10s %s" % (r[0], r[1]))
    dups = c.execute("select count(*) from work_item where title like 'owner asked by text:%' "
                     "and state <> 'dropped'").fetchone()[0]
    print("  proof-artifact items still open (should be 0): %s" % dups)
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
