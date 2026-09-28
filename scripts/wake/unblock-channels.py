#!/usr/bin/env python3
"""Unblock the two items whose blocker has resolved, and be precise about what is proven versus not.

WHAT THE RECORD SHOWS, and it is a good example of the system working:

  #7 (the responder answers an owner request with silence). A shift found the REAL cause, which I had wrong:
  his two texts of 2026-09-28 (15:57:18Z and 15:58:56Z) WERE seen - the tick said `2 to decide` - and were
  DROPPED as state=ignored because the permissions row then read `allow=never` (Chips Zebrowski/friend/never).
  That row was corrected at 18:39:39Z, the send gate now reports OPEN, and the inbound path is proven in
  production by his own 22:43 text landing as housekeeping#76. The blocker named was "owner approval to let
  the responder send acknowledgement texts" - and that specific blocker is now moot, because the
  acknowledgement was REPLACED by the top-question reply (his own 22:43 request: "Text me the top question
  you have for me right now").

  #8 (no path from a finished shift back to his phone). A shift BUILT and WIRED it: `shift-report.py`
  (record/decision) is wired into the shift contract, STEP 4 calls `record`, STEP 7 calls `decision`, and the
  ungated `textsend.py send --to ... --send` command is GONE from the contract. Its named blocker was
  per-message approval of exact words - and that has now HAPPENED: the owner was shown the library body and
  said "send whatever you need to without overwhelming me", and the message was sent and Twilio confirms
  `delivered`.

SO #7 is DONE and #8's blocker is resolved - but I will not pretend #8 is finished: its definition of done
asks for the outcome actually texted with a quoted message id, and while one real message has now gone out on
this channel, it went out from the manager seat, not from the woken-shift path. The honest move is to unblock
#8 to `todo` with that distinction written down, so the next shift verifies the autonomous path rather than
re-doing it.

Usage: python3 unblock-channels.py [--apply]
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from datetime import datetime, timezone

DB = "/home/zabz/work/work.db"
CLOSE7 = dict(
    did="Unblocked and closed. The blocker named was owner approval for acknowledgement texts; that "
        "acknowledgement was REPLACED by a reply carrying the top unasked question from the owner's queue, "
        "which is what he asked for himself at 22:43Z ('Text me the top question you have for me right "
        "now'). The real defect a shift found under it - his 15:57/15:58 texts were dropped as "
        "state=ignored because the permissions row read allow=never - was corrected at 18:39:39Z, and the "
        "inbound path is now proven IN PRODUCTION: his own 22:43 text arrived and landed as "
        "housekeeping#76.",
    proof="python3 ~/bin/sms-responder.py run --dry-run ; sqlite3 ~/personal-secretary-mvp/data/secretary.db "
          "\"select id,direction,body from sms_log where id=1025\" ; sqlite3 ~/work/work.db "
          "\"select id,project,title from work_item where id=76\"",
    result="synthetic text on a throwaway store -> filed as lpt-website#42 (routing proof). REAL text from "
           "him -> filed as housekeeping#76 (production proof). Send gate: 'OPEN - recipient is the owner's "
           "own number'. First real outbound message sent 22:56:27Z, Twilio API reports "
           "status=delivered, error=none, price=-0.01660 USD.",
    left="The reply path is wired but has not yet fired on a live text, because it needs him to text again - "
         "see item #8.",
)
UNBLOCK8 = dict(
    did="Unblocked. Its named blocker (per-message approval of exact words) has now HAPPENED: the owner was "
        "shown the exact library-collection body and replied 'send whatever you need to without "
        "overwhelming me'; that message was sent at 22:56:27Z and Twilio reports delivered. The mechanism "
        "this item asked for is built AND wired into the contract by a shift - shift-report.py record at "
        "STEP 4, decision at STEP 7, and the ungated textsend command is gone.",
    proof="grep -n 'shift-report.py' /home/zabz/bin/sources/project-keepalive.py ; "
          "grep -c 'textsend.py send --to' /home/zabz/bin/sources/project-keepalive.py",
    result="shift-report.py decision refuses without --approved-by-owner (4 refusal sites); the rendered "
           "contract contains the gated instruction and does NOT contain the ungated send; one real message "
           "delivered on this channel.",
    left="THE ONE THING LEFT, stated precisely: the message that went out came from the manager seat, not "
         "from the woken-shift path, so what remains is to verify the AUTONOMOUS path end to end - have a "
         "shift (or the responder on a live owner text) send a message through shift-report.py, and quote "
         "the resulting message id here. That needs an owner text or a shift with something genuinely his. "
         "Do NOT rebuild anything; the mechanism is in place.",
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    a = ap.parse_args()
    if not a.apply:
        print("dry run: would close #7 done, and move #8 blocked -> todo, with the evidence above")
        return 0
    c = sqlite3.connect(DB, timeout=30)
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # #7 -> done, recorded as an attempt so the proof is durable.
    c.execute("INSERT INTO attempt (item, worker, started_at, ended_at, state_after, did, proof, result, "
              "left_over) VALUES (?,?,?,?,?,?,?,?,?)",
              (7, "manager-unblock", now, now, "done", CLOSE7["did"], CLOSE7["proof"], CLOSE7["result"],
               CLOSE7["left"]))
    c.execute("UPDATE work_item SET state='done', blocked_on=NULL, done_at=?, updated_at=? WHERE id=7",
              (now, now))
    print("#7 -> done (attempt row written with the proof)")

    # #8 -> todo, blocker cleared, with the precise remainder recorded.
    c.execute("INSERT INTO attempt (item, worker, started_at, ended_at, state_after, did, proof, result, "
              "left_over) VALUES (?,?,?,?,?,?,?,?,?)",
              (8, "manager-unblock", now, now, "todo", UNBLOCK8["did"], UNBLOCK8["proof"], UNBLOCK8["result"],
               UNBLOCK8["left"]))
    c.execute("UPDATE work_item SET state='todo', blocked_on=NULL, updated_at=? WHERE id=8", (now,))
    print("#8 -> todo (blocker cleared; remainder written down)")

    # #7's inbound half also had a duplicate of the same finding in #76's territory; leave #76 alone.
    c.commit()
    print("\n=== the board now ===")
    for r in c.execute("select state, count(*) from work_item group by 1 order by 2 desc"):
        print("  %-10s %s" % (r[0], r[1]))
    print("  still blocked:", [r[0] for r in c.execute(
        "select id from work_item where state='blocked' order by id")] or "none")
    c.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
