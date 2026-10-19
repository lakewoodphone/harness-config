#!/usr/bin/env python3
"""is-the-channel-open.py - is the app-side gate blocking, or is nothing trying to send?

Two turns are open (row 151 at 14:12, row 152 at 16:42) and nothing has been sent for an hour. Two
possible reasons, and they are not the same sentence:
  (a) the gate is holding the channel shut on an unanswered turn, or
  (b) the turns have lapsed (a turn with no question ends after a grace) and nothing wants to send.

This answers it from the gate's own functions, then exercises `gate()` itself - the half of the
channel the relay tests never touch - with four bodies on a throwaway database.
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/opt/company")
spec = importlib.util.spec_from_file_location("owner_text_under_test",
                                              "/opt/company/app/owner_text.py")
OT = importlib.util.module_from_spec(spec)
sys.modules["owner_text_under_test"] = OT
spec.loader.exec_module(OT)

AUTH = "/root/authority.db"
print("== the two open turns, judged by the gate's own turn_has_ended()")
c = sqlite3.connect("file:%s?mode=ro" % AUTH, uri=True)
c.row_factory = sqlite3.Row
for r in c.execute("select id,sent_at,body from owner_text_turn where answered_at is null "
                   "order by sent_at desc limit 3"):
    rec = {"sent_at": r["sent_at"], "body": r["body"] or "", "answered_at": None}
    ended, why = OT.turn_has_ended(rec)
    print("  #%s %s expects_answer=%-5s ended=%-5s  %s"
          % (r["id"], str(r["sent_at"])[:19], OT.expects_answer(r["body"] or ""),
             ended, str(why)[:70]))
c.close()

print()
print("== the gate itself, on a throwaway store")
TMP = tempfile.mkdtemp(prefix="gate_")
DB = os.path.join(TMP, "probe.db")
URL = "sqlite:///" + DB
OT.ensure_schema(URL)

class S:
    pass

settings = S()
for attr, val in (("database_url", URL), ("owner_text_max_chars", 400),
                  ("owner_text_min_gap_minutes", 20), ("owner_text_reply_window_hours", 12),
                  ("owner_text_turn_grace_minutes", 5), ("owner_text_similar_hold_minutes", 60),
                  ("owner_text_no_question_grace_minutes", 45),
                  ("owner_text_priority_free_play", False)):
    setattr(settings, attr, val)

CASES = [
    ("a plain result", "The Q3 ST-50 is filed. Confirmation 4471. Nothing needed from you."),
    ("a real question", "The Fisher SD card is not in the intake bins. Post the 50 dollar deposit, "
                        "or keep looking?"),
    ("agent prose with a path", "Reminder: EXECUTE: pay him. Record date in lpt-hub/docs/pay.md"),
    ("a credential ask", "Send me the NJ Premier Business Services login and I will file it."),
]
for label, body in CASES:
    try:
        verdict = OT.gate(URL, body=body, reason="send_message",
                          urgency="normal", settings=settings)
        allowed = getattr(verdict, "allowed", None)
        why = getattr(verdict, "reason", "") or getattr(verdict, "why", "")
        print("  %-26s allowed=%-5s %s" % (label, allowed, str(why)[:70]))
    except Exception as exc:                                   # noqa: BLE001
        print("  %-26s RAISED %s: %s" % (label, type(exc).__name__, str(exc)[:60]))
