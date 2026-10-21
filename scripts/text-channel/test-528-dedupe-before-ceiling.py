#!/usr/bin/env python3
"""Item 528: three identical OVER-LENGTH submissions -> ONE transmission.

Before 2026-10-21 `submit()` evaluated the ceiling BEFORE the duplicate pair, so a
body over the owner's one-text ceiling was always a fresh SEND: attempts 74/75/76
were one 377-char family message recorded and transmitted three times. This test
submits the same over-length body three times, 90 s apart, with the first one
marked sent, and asserts the second and third are DEDUPE/dup-sent and that only
ONE row in the store carries verdict='SEND' for that body hash.

Run: python3 /root/bin/test-528-dedupe-before-ceiling.py
"""
import os
import sys
import tempfile
from datetime import timedelta

sys.path.insert(0, os.environ.get("RELAY_DIR", "/root/bin"))

tmp = tempfile.mkdtemp(prefix="relay-528-")
os.environ["OWNER_TEXT_RELAY_DB"] = os.path.join(tmp, "relay.db")

import owner_text_relay as relay  # noqa: E402

body = "The quarterly summary is ready for your review. " * 12
assert len(body) > relay.MAX_CHARS, (len(body), relay.MAX_CHARS)

# Deterministic clock: 90 s between submissions, all well inside the dup window.
base = relay._now()
clock = {"t": base}
relay._now = lambda: clock["t"]
# Isolate the ordering under test: the topic ledger (added 2026-10-19) would
# also suppress a repeat, which is a different rule and has its own coverage.
relay._topic_verdict = lambda *a, **k: None

def submit_at(seconds):
    clock["t"] = base + timedelta(seconds=seconds)
    return relay.submit(
        door="test528", subsystem="test528", body=body, reason="test528",
        urgency="urgent",  # quiet hours must not decide this test
    )

r1 = submit_at(0)
print("1:", r1["verdict"], r1["reason"], "aid", r1["attempt_id"])
assert r1["verdict"] == "SEND" and r1["reason"] == "too-long", r1
relay.record_sent(r1["attempt_id"], sid="SM528TEST1")

r2 = submit_at(90)
print("2:", r2["verdict"], r2["reason"], "holds", r2["holds"])
assert r2["verdict"] == "DEDUPE" and r2["reason"] == "dup-sent", r2
assert r1["attempt_id"] in r2["holds"], r2

r3 = submit_at(180)
print("3:", r3["verdict"], r3["reason"], "holds", r3["holds"])
assert r3["verdict"] == "DEDUPE" and r3["reason"] == "dup-sent", r3
assert r1["attempt_id"] in r3["holds"], r3

c = relay.connect()
rows = c.execute(
    "SELECT attempt_id, verdict, verdict_reason FROM attempt WHERE body_hash=? "
    "ORDER BY attempt_id", (r1["body_hash"],)
).fetchall()
sends = [dict(r) for r in rows if r["verdict"] == "SEND"]
print("rows:", [dict(r) for r in rows])
assert len(sends) == 1, sends
assert sends[0]["verdict_reason"] == "too-long", sends
print("PASS: 3 submissions ->", len(rows), "rows,", len(sends), "SEND")