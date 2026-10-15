"""Pins the machine-acknowledgement class in comms-search.py.

ONE RULE, TWO HALVES, AND THIS TEST IS THE PROOF OF BOTH:

    the shop's SMS auto-responder must NOT close a thread,
    a real human outbound MUST still close it.

The auto-responder is deliberate shop policy (owner ruling 2026-10-13: "it's dialpad
auto reply and it's there on purpose"), so nothing here asks for it to be removed, gated
or changed. What it must not be is a REPLY: the question this engine answers is "whose
last word was theirs and has a PERSON replied", and a robot saying "we'll text you back
when we're in" is not a person.

BOTH ORDERINGS ARE COVERED ON PURPOSE. The raw index sometimes timestamps the auto-reply
BEFORE the message it answers — measured 2026-10-07 on (845) 558-8440: the bot's reply is
ts 1791406131.415 and the customer's "What are your hours today?" is ts 1791406131.748 —
so a test that only covered "bot after customer" would pass while the list stayed wrong.

Run directly:  python3 tests/test_comms_machine_ack.py
"""
import importlib.util
import os
import sqlite3
import sys
import tempfile
from pathlib import Path

ENGINE = os.environ.get("COMMS_SEARCH",
                        "/root/.fsearch/comms-search.py")

spec = importlib.util.spec_from_file_location("comms_search", ENGINE)
cs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cs)

T = 1792000000.0
DAY = "2026-10-14"

# The six distinct auto-responder texts actually sent between 2026-07-15 and 2026-10-14,
# copied verbatim out of ~/.fsearch/comms.db. Every one of them must be recognised, and
# the body differs in hours, in drop-off wording and in whether the address line is
# present — which is why the class is anchored on the greeting alone.
VARIANTS = [
    "Thanks for texting Lakewood Phone & Tech. We're closed right now. Our hours are "
    "Mon-Thu 10:30-5:30, Fri 10:30-1:00. We'll reach out when we're back in. We also "
    "have a 24-hour secure hallway drop-off at 1001 West Kennedy Blvd in the basement "
    "left side of house \u2014 just leave your device with a note.",
    "Thanks for texting Lakewood Phone & Tech. We're closed right now. Our walk-in "
    "hours are Mon-Thu 10:30-5:30, Fri 10:30-1:00. We'll reach out when we're back in. "
    "We also have a 24-hour secure hallway drop-off at 1001 West Kennedy Blvd in the "
    "basement left side of house \u2014 just leave your device with a note.",
    "Thanks for texting Lakewood Phone & Tech. We're closed right now. Our walk-in "
    "hours are Mon, Tue, & Thu 10:30-5:30, Fri 10:30-1:00. We'll reach out when we're "
    "back in. We also have a 24-hour secure hallway drop-off at 1001 West Kennedy Blvd "
    "in the basement left side of house \u2014 just leave your device with a note.",
    "Thanks for texting Lakewood Phone & Tech. We're closed right now. Our walk-in "
    "hours are Sun 12-4,  Tue & Thu 10:30-5:30. Mon & Wed drop-off only. We also have a "
    "24-hour secure hallway drop-off at 1001 West Kennedy Blvd in the basement left "
    "side of house \u2014 just leave your device with a note.",
    "Thanks for texting Lakewood Phone & Tech. Our walk-in hours are Sunday 12-4, and "
    "Tuesday and Thursday 10:30-5:30. You can drop your device off any time at our "
    "secure drop-off and we'll get started on it. We'll text you back when we're in.",
    "Thanks for texting Lakewood Phone & Tech. Our walk-in hours are Sunday 12-4, and "
    "Tuesday and Thursday 10:30-5:30. You can drop your device off any time at our "
    "secure drop-off and we'll get started on it.\n1001 W. Kennedy Blvd Basement left "
    "side of house.\nWe'll text you back when we're in.",
]

SCHEMA = """
CREATE TABLE comms (
    id INTEGER PRIMARY KEY, kind TEXT NOT NULL, ref TEXT, ts REAL, day TEXT,
    direction TEXT, counterparty TEXT, address TEXT, subject TEXT, text TEXT NOT NULL,
    meta TEXT, source_table TEXT);
CREATE TABLE meta (key TEXT, value TEXT);
CREATE TABLE person_alias (person_key TEXT, alias_kind TEXT, alias_value TEXT, reason TEXT);
CREATE TABLE people (person_key TEXT PRIMARY KEY, display_name TEXT, phones TEXT,
    names TEXT, kinds TEXT, emails TEXT);
"""


def _build():
    tmp = tempfile.mkdtemp(prefix="c8-machine-ack-")
    db = os.path.join(tmp, "comms.db")
    con = sqlite3.connect(db)
    con.executescript(SCHEMA)
    con.execute("INSERT INTO meta(key,value) VALUES('last_index','2099-01-01T00:00:00+00:00')")
    con.commit()
    con.close()
    return db


def add(db, ts, direction, text, kind="sms", address="18485550001", who="(848) 555-0001"):
    con = sqlite3.connect(db)
    con.execute("INSERT INTO comms(kind,direction,ts,day,text,counterparty,address,"
                "source_table) VALUES(?,?,?,?,?,?,?,'test')",
                (kind, direction, ts, DAY, text, who, address))
    con.commit()
    con.close()


def parties(db, **kw):
    res = cs.waiting(db, days=3650, limit=200)
    assert res["ok"], res
    return res, {cs._digits(w["party"]) for w in res["waiting"]}


# ── the classifier, per variant ───────────────────────────────────────────────
def test_every_variant_is_a_machine_acknowledgement():
    for i, v in enumerate(VARIANTS, 1):
        assert cs._is_machine_acknowledgement(v), f"variant {i} not recognised"


def test_a_human_reply_is_not_a_machine_acknowledgement():
    assert not cs._is_machine_acknowledgement("Thanks for texting Lakewood Phone & Tech.")
    assert not cs._is_machine_acknowledgement(
        "Thanks for texting Lakewood Phone & Tech. Are you around for a call?")
    assert not cs._is_machine_acknowledgement("Thanks")
    assert not cs._is_machine_acknowledgement(
        "Hi, this is Moshe from Lakewood Phone & Tech. Sorry we missed your call!")
    assert not cs._is_machine_acknowledgement(
        'Great news rivky! Your repair order #WO2606110004 is ready for pickup.')


# ── the predicate: the bot must not close a thread ────────────────────────────
def test_auto_reply_after_the_question_does_not_close_the_thread():
    db = _build()
    add(db, T, "inbound", "Where is my laptop?")
    add(db, T + 2, "outbound", VARIANTS[4])          # the live variant
    res, p = parties(db)
    assert "18485550001" in p, res["waiting"]
    assert res["reopened_by_machine_ack"] == 1


def test_auto_reply_timestamped_BEFORE_the_question_does_not_close_it():
    # The ordering the raw index actually produces sometimes; see the module docstring.
    db = _build()
    add(db, T, "inbound", "What are your hours today?")
    add(db, T - 0.33, "outbound", VARIANTS[4])
    _res, p = parties(db)
    assert "18485550001" in p


def test_a_real_human_outbound_still_closes_the_thread():
    db = _build()
    add(db, T, "inbound", "Where is my laptop?")
    add(db, T + 60, "outbound", "It is on the pickup shelf, come by any time. - Daniel")
    _res, p = parties(db)
    assert "18485550001" not in p


def test_bot_first_then_a_person_still_closes_the_thread():
    db = _build()
    add(db, T, "inbound", "Where is my laptop?")
    add(db, T + 5, "outbound", VARIANTS[0])
    add(db, T + 50, "outbound", "Found it, it is on the shelf. - Daniel")
    _res, p = parties(db)
    assert "18485550001" not in p


def test_a_person_then_the_bot_still_closes_the_thread():
    db = _build()
    add(db, T, "inbound", "Where is my laptop?")
    add(db, T + 10, "outbound", "Looking into it now. - Daniel")
    add(db, T + 20, "outbound", VARIANTS[5])
    _res, p = parties(db)
    assert "18485550001" not in p


def test_all_six_variants_fail_to_close_their_thread():
    db = _build()
    for i, v in enumerate(VARIANTS):
        num = f"1848555{i:04d}"
        add(db, T + i, "inbound", "Do you fix screens?", address=num, who=num)
        add(db, T + i + 1, "outbound", v, address=num, who=num)
    res, p = parties(db)
    assert len(p) == len(VARIANTS), res["waiting"]
    assert res["reopened_by_machine_ack"] == len(VARIANTS)


# ── the bot stays visible, and the other classes are untouched ────────────────
def test_the_bots_message_is_still_in_the_thread():
    db = _build()
    add(db, T, "inbound", "Where is my laptop?")
    add(db, T + 2, "outbound", VARIANTS[4])
    th = cs.thread(db, "18485550001", limit=50)
    texts = " ".join(r["text"] or "" for r in th["results"])
    assert VARIANTS[4] in texts, "the auto-reply must not be hidden from the thread"
    assert "Where is my laptop?" in texts


def test_a_customer_thanks_is_still_acknowledged_not_waiting():
    db = _build()
    add(db, T, "inbound", "Perfect thank you so much")
    add(db, T + 1, "outbound", VARIANTS[4])
    res, p = parties(db)
    assert "18485550001" not in p
    assert res["closed_by_acknowledgement"] == 1


def test_a_blank_voicemail_is_not_someone_waiting_to_be_answered():
    db = _build()
    add(db, T, "inbound", "[voicemail, no transcript] (848) 555-0001 18485550001",
        kind="voicemail")
    res, p = parties(db)
    assert p == set()
    assert res["total_missed_calls"] == 1
    assert cs._is_blank_voicemail("[voicemail, no transcript] x")


def _main():
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"PASS {name}")
        except AssertionError as exc:
            failed += 1
            print(f"FAIL {name}: {exc}")
        except Exception as exc:                    # a missing function/key = also a fail
            failed += 1
            print(f"FAIL {name}: {type(exc).__name__}: {exc}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(_main())
