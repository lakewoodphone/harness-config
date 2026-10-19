#!/usr/bin/env python3
"""test-owner-topic.py — the acceptance test for the topic ledger.

The owner's complaint is not abstract; it has four bodies in his thread. So the first test
replays those four EXACT bodies and asserts the ledger would have stopped the last three.

Every test runs against a throwaway database in a temp directory. Nothing here touches
/root/.owner-text/relay.db, and the whole file is safe to run on any box.

    python3 test-owner-topic.py            # 0 = all passed
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import importlib.util  # noqa: E402

spec = importlib.util.spec_from_file_location("owner_topic", os.path.join(HERE, "owner_topic.py"))
owner_topic = importlib.util.module_from_spec(spec)
spec.loader.exec_module(owner_topic)

FAILURES = []
CHECKS = [0]


def check(condition, label, detail=""):
    CHECKS[0] += 1
    if not condition:
        FAILURES.append("%s %s" % (label, detail))
        print("FAIL %s %s" % (label, detail))
    else:
        print("ok   %s" % label)


# The four texts the owner actually received, verbatim, for one payment.
WEINBERG = [
    "⏰ Reminder: EXECUTE: Pay Yisroel Weinberg $597.29 net CASH settlement (owner decided "
    "after Sukkot). Sukkot ended Sun 2026-10-04. Record date+amount in lpt-hub.",
    "⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement (owner decided: after "
    "Sukkot). Actionable from Mon 2026-10-05. Record date+amount in lpt-hub.",
    "⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement (owner decided: after "
    "Sukkot). Sukkot ends Sun 2026-10-04, so this is actionable today.",
    "⏰ Reminder: OWNER ACTION: Pay Yisroel Weinberg $597.29 net CASH settlement (owner "
    "decided 2026-09-30, due after Sukkot). After paying, reply so I can log it.",
]
T0 = datetime(2026, 10, 5, 21, 3, tzinfo=timezone.utc)


def fresh():
    d = tempfile.mkdtemp(prefix="_owner_topic_test_")
    return os.path.join(d, "relay.db")


# --------------------------------------------------------------------------- #
# 1. The four Weinberg reminders
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
topics = [owner_topic.normalise_topic(b, "reminder:52")[0] for b in WEINBERG]
check(len(set(topics)) == 1, "all four wordings derive ONE topic", str(set(topics)))
check(topics[0] == "money:597.29", "the topic is the money fingerprint", topics[0])

verdicts = []
sent_at = []
for i, body in enumerate(WEINBERG):
    when = T0 + timedelta(minutes=[0, 45, 90, 60 * 24 * 3][i])
    v = owner_topic.admit(body, reason="reminder:52", subsystem="reminder", now=when, conn=conn)
    verdicts.append(v["code"])
    if v["allow"]:
        sent_at.append(when)
        owner_topic.record(body, reason="reminder:52", subsystem="reminder", now=when, conn=conn)

check(verdicts[0] == "ok", "first Weinberg reminder goes out", verdicts[0])
check(verdicts[1] == "topic_cooldown", "2nd (45 min later) refused", verdicts[1])
check(verdicts[2] == "topic_cooldown", "3rd (90 min later) refused", verdicts[2])
# The 4th is three days later. A daily nudge on an unpaid settlement is CORRECT behaviour --
# what was wrong was four texts in 61 hours, three of them inside 90 minutes. So the invariant
# is not "one send ever", it is "no two sends closer together than the window".
check(verdicts[3] == "ok", "4th (3 days later) is a legitimate follow-up, not a repeat", verdicts[3])
gaps = [(b - a).total_seconds() / 60.0 for a, b in zip(sent_at, sent_at[1:])]
check(all(g >= owner_topic.window_minutes("reminder") for g in gaps),
      "no two sends inside the 20h window", str(gaps))
check(len(sent_at) == 2, "4 texts collapse to 2 (3 of 4 refused)", str(len(sent_at)))
conn.close()

# --------------------------------------------------------------------------- #
# 2. A different payment is a different topic
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
a = owner_topic.admit("⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement",
                      reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
owner_topic.record("⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement",
                   reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
b = owner_topic.admit("⏰ Reminder: Chase CC (...9650) payment is due 10/11/2026 - 1,204.00",
                      reason="reminder:77", subsystem="reminder", now=T0, conn=conn)
check(b["allow"] and b["topic"] == "money:1204.00", "a different amount is allowed", b["topic"])
conn.close()

# --------------------------------------------------------------------------- #
# 3. closed vs cooldown are different sentences
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
body = "⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement"
v = owner_topic.admit(body, reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
check(v["allow"], "open topic admits", v["code"])
owner_topic.record(body, reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
owner_topic.close_topic("money:597.29", "answered", now=T0, conn=conn)
v = owner_topic.admit(body, reason="reminder:52", subsystem="reminder", now=T0 + timedelta(days=9),
                      conn=conn)
check(v["code"] == "topic_closed", "answered topic is CLOSED, not merely cooling", v["code"])
check("answered" in v["detail"], "the detail says answered, not 'later'", v["detail"])
conn.close()

# --------------------------------------------------------------------------- #
# 4. a refusal must not extend the window
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
body = "⏰ Reminder: Pay Yisroel Weinberg $597.29 net CASH settlement"
owner_topic.admit(body, reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
owner_topic.record(body, reason="reminder:52", subsystem="reminder", now=T0, conn=conn)
for i in range(5):
    owner_topic.note_refusal(body, reason="reminder:52", subsystem="reminder",
                             now=T0 + timedelta(minutes=10 * i), conn=conn)
v = owner_topic.admit(body, reason="reminder:52", subsystem="reminder",
                      now=T0 + timedelta(minutes=1210), conn=conn)
check(v["allow"], "after the 20h window, a refusal-heavy topic is allowed again", v["code"])
row = owner_topic.row_for("money:597.29", "reminder", conn=conn)
check(row["refused"] == 5, "refusals are counted", str(row["refused"]))
check(row["sends"] == 1, "refusals did not inflate sends", str(row["sends"]))
conn.close()

# --------------------------------------------------------------------------- #
# 5. families carry their own windows
# --------------------------------------------------------------------------- #
check(owner_topic.family_of("reminder:12") == "reminder", "reminder family")
check(owner_topic.family_of("cfo_ask") == "ask", "cfo_ask is an ask")
check(owner_topic.family_of("", "owner-ask") == "ask", "owner-ask subsystem is an ask")
check(owner_topic.family_of("security alert") == "alert", "security is an alert")
check(owner_topic.window_minutes("reminder") == 1200, "reminder window 20h")
check(owner_topic.window_minutes("ask") == 4320, "ask window 72h")
check(owner_topic.window_minutes("alert") == 60, "alert window 1h")

# --------------------------------------------------------------------------- #
# 6. the weak path: restatement of one sentence
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
hold = "received your message. i am processing it."
v1 = owner_topic.admit(hold, now=T0, conn=conn)
owner_topic.record(hold, now=T0, conn=conn)
v2 = owner_topic.admit(hold, now=T0 + timedelta(minutes=1), conn=conn)
check(v1["topic"].startswith("say:"), "a bare hold gets a weak say: topic", v1["topic"])
check(v2["code"] == "topic_cooldown", "the 10th copy of the hold would be refused", v2["code"])
conn.close()

# --------------------------------------------------------------------------- #
# 7. identities that must NOT be conflated
# --------------------------------------------------------------------------- #
check(owner_topic.derive_topic("WO2602180002 refund is ready") == "case:WO2602180002",
      "a work order derives from its id, not from noise")
check(owner_topic.derive_topic("Task #26089: did the rash clear?") == "task:26089",
      "a task id is its own topic")
check(owner_topic.derive_topic("ok") == "", "a two-letter body has no topic")
v = owner_topic.admit("ok", now=T0, conn=None)
check(v["code"] == "no_topic" and v["allow"], "no topic means allowed, never blocked",
      v["code"])

# --------------------------------------------------------------------------- #
# 8. a broken store must never block a message the owner is owed
# --------------------------------------------------------------------------- #
v = owner_topic.admit("⏰ Reminder: Pay Yisroel Weinberg $597.29", reason="reminder:52",
                      subsystem="reminder", now=T0, conn=None)
check(v["allow"], "missing store: allowed (fails open)", v["code"])
broken = owner_topic.record("x", reason="reminder:1", conn=None)
check(True, "record on a missing dir does not raise")

# --------------------------------------------------------------------------- #
# 9. THE FALSE-POSITIVE THAT MATTERS: a correction must not be silenced
# --------------------------------------------------------------------------- #
db = fresh()
conn = owner_topic.connect(db)
alarm = "Telnyx balance at -$0.01 - services suspend at $0 Yes?"
owner_topic.admit(alarm, reason="alert:telnyx", subsystem="alert", now=T0, conn=conn)
owner_topic.record(alarm, reason="alert:telnyx", subsystem="alert", now=T0, conn=conn)
fix = "That screenshot settles it - 103.50 available balance, not -0.01. My Telnyx alert was wrong."
v = owner_topic.admit(fix, reason="alert:telnyx", subsystem="alert",
                      now=T0 + timedelta(minutes=3), conn=conn)
check(v["allow"], "a CORRECTION reaches him even inside the alert window", v["code"] + " " + v["topic"])

db2 = fresh()
c2 = owner_topic.connect(db2)
rem = "Reminder: Pay Yisroel Weinberg 597.29 net CASH settlement"
st = "Paid the 597.29 to Weinberg today, recorded in the ledger."
owner_topic.admit(rem, reason="reminder:52", subsystem="reminder", now=T0, conn=c2)
owner_topic.record(rem, reason="reminder:52", subsystem="reminder", now=T0, conn=c2)
v = owner_topic.admit(st, reason="status:payment", subsystem="status",
                      now=T0 + timedelta(minutes=5), conn=c2)
check(v["allow"], "a status line about the same money is not the same topic", v["code"])
c2.close()

print()
print("checks=%d failures=%d" % (CHECKS[0], len(FAILURES)))
if FAILURES:
    for f in FAILURES:
        print(" - " + f)
    sys.exit(1)
print("ALL PASS")
