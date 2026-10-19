#!/usr/bin/env python3
"""prove-one-text-one-turn.py - two records of the same sid must be ONE turn, answered or not.

Before the change the second record, made after his reply closed the first row, found nothing and
inserted a second turn for the same text. One reply closes one row; the other keeps the channel
shut. This drives the real `record_outbound` on a throwaway database.
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile

TMP = tempfile.mkdtemp(prefix="turn_")
DB = os.path.join(TMP, "probe.db")
URL = "sqlite:///" + DB
sys.path.insert(0, "/opt/company")

spec = importlib.util.spec_from_file_location("owner_text_under_test",
                                              "/opt/company/app/owner_text.py")
OT = importlib.util.module_from_spec(spec)
sys.modules["owner_text_under_test"] = OT
spec.loader.exec_module(OT)

OT.ensure_schema(URL)
SID = "SMprobe-one-text-one-turn"


def count_rows():
    c = sqlite3.connect(DB)
    try:
        return c.execute("select count(*) from owner_text_turn").fetchone()[0]
    finally:
        c.close()


def close_all():
    c = sqlite3.connect(DB)
    try:
        c.execute("update owner_text_turn set answered_at=datetime('now') "
                  "where answered_at is null")
        c.commit()
    finally:
        c.close()


bad = 0
print("store (throwaway): %s" % DB)

first = OT.record_outbound(URL, body="The ST-50 is filed.", reason="send_message", sid=SID)
print("  first record          -> id=%s rows=%d" % (first, count_rows()))
bad += 0 if count_rows() == 1 else 1

second = OT.record_outbound(URL, body="The ST-50 is filed.", reason="owner_sms_reply", sid=SID)
print("  same sid, turn OPEN   -> id=%s rows=%d  (must be the same id, one row)"
      % (second, count_rows()))
bad += 0 if (second == first and count_rows() == 1) else 1

close_all()
print("  ...he answers; the turn is now CLOSED")

third = OT.record_outbound(URL, body="The ST-50 is filed.", reason="owner_sms_reply", sid=SID)
rows = count_rows()
print("  same sid, turn CLOSED -> id=%s rows=%d  (this is the case that used to double)" % (third, rows))
bad += 0 if (third == first and rows == 1) else 1

print()
print("  and the same BODY with NO sid is still free to open a NEW turn:")
close_all()
fourth = OT.record_outbound(URL, body="The ST-50 is filed.", reason="send_message", sid="")
print("    no-sid record       -> id=%s rows=%d  (a second turn is correct here)" % (fourth, count_rows()))
bad += 0 if count_rows() == 2 else 1

print()
print("RESULT:", "PASS" if not bad else "FAIL (%d)" % bad)
raise SystemExit(0 if not bad else 1)
