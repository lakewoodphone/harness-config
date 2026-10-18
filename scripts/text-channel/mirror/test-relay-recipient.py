#!/usr/bin/env python3
"""test-relay-recipient.py — prove the recipient-aware ceiling without touching the live store.

Run:  python3 test-relay-recipient.py
Exit: 0 all passed, 1 any failure. Prints "N passed".

What it pins (each is a real incident or a real risk):

  1. A body over the owner's ceiling still yields SEND/too-long  — the 2026-10-14 decision,
     which exists because `TOO_LONG` refused messages doors had already committed to.
  2. The SAME body addressed to a third party no longer reports too-long, because the 320
     ceiling is about how the owner reads, not a transport limit. This is attempts 74/75:
     a 377-char message he asked us to send to a family member, recorded SEND/too-long and
     then stranded by the owner's rate floor (sms_log 4280/4281).
  3. `to_number` is recorded on the attempt row, so "who got this" is answerable from the
     ledger for the first time.
  4. An OLD store with no `to_number` column migrates forward on connect and loses nothing.
  5. A third-party body over Twilio's limit is recorded too-long (it really would fail).
  6. Existing dedupe behaviour is unchanged by the new column.
"""

import importlib.util
import os
import sqlite3
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
PASSED = 0
FAILED = []


def ok(name, cond, detail=""):
    global PASSED
    if cond:
        PASSED += 1
        print(f"  PASS  {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL  {name}  {detail}")


def load(path=None):
    spec = importlib.util.spec_from_file_location("relay_under_test", path or os.path.join(HERE, "owner_text_relay.py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    tmp = tempfile.mkdtemp(prefix="relay-test-")
    db = os.path.join(tmp, "relay.db")
    os.environ["OWNER_TEXT_RELAY_DB"] = db
    os.environ["OWNER_PHONE_NUMBERS"] = "+18483897895"
    relay = load()

    OWNER = "+18483897895"
    FAMILY = "+18482245096"
    LONG = ("Hi, this is Eliyahu's assistant. He asked me to check one thing with you.\n\n"
            "There's an Audible membership charging 15.94 a month to the Amex, on the "
            "chevedy@gmail.com account. It's showing 7 credits unused, so roughly seven "
            "months of membership with nothing spent.\n\nIs that one you want to keep?")
    LONG = LONG.ljust(377, " ")      # the incident body was exactly 377 chars
    assert len(LONG) == 377, len(LONG)

    print("1/6 owner over ceiling keeps the documented SEND/too-long")
    r1 = relay.submit("app", "test.owner", LONG, to=OWNER)
    ok("verdict is SEND", r1["verdict"] == "SEND", r1)
    ok("reason is too-long", r1["reason"] == "too-long", r1)
    ok("body length is 377", len(LONG) == 377, len(LONG))

    print("2/6 the same body to a third party is not too-long")
    r2 = relay.submit("family_chat", "test.third", LONG, to=FAMILY, dedupe_disabled=True)
    ok("verdict is SEND", r2["verdict"] == "SEND", r2)
    ok("reason is NOT too-long", r2["reason"] != "too-long", r2)
    ok("attempt id returned", bool(r2.get("attempt_id")), r2)

    print("3/6 recipient is recorded on the attempt row")
    con = sqlite3.connect(db)
    con.row_factory = sqlite3.Row
    row = con.execute("SELECT to_number FROM attempt WHERE attempt_id=?", (r2["attempt_id"],)).fetchone()
    ok("to_number == family", row and row["to_number"] == FAMILY, dict(row) if row else None)
    row1 = con.execute("SELECT to_number FROM attempt WHERE attempt_id=?", (r1["attempt_id"],)).fetchone()
    ok("to_number == owner", row1 and row1["to_number"] == OWNER, dict(row1) if row1 else None)
    con.close()

    print("4/6 an old store without to_number migrates forward on connect")
    old = os.path.join(tmp, "old.db")
    c = sqlite3.connect(old)
    old_schema = "\n".join(l for l in relay.SCHEMA_SQL.splitlines()
                           if "to_number" not in l).replace(",\n)", "\n)")
    c.executescript(old_schema)
    c.execute("INSERT INTO attempt (at,door,subsystem,body,body_hash,verdict,verdict_reason) "
              "VALUES ('2026-10-15T00:00:00.000000Z','app','legacy','legacy body','h','SEND','ok')")
    c.commit()
    before = c.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]
    cols_before = {x[1] for x in c.execute("PRAGMA table_info(attempt)")}
    c.close()
    ok("old store really lacks the column", "to_number" not in cols_before, cols_before)
    relay2 = load()
    con2 = relay2.connect(old)
    relay2._ensure_columns(con2)
    cols_after = {x[1] for x in con2.execute("PRAGMA table_info(attempt)")}
    after = con2.execute("SELECT COUNT(*) FROM attempt").fetchone()[0]
    con2.close()
    ok("column added", "to_number" in cols_after, cols_after)
    ok("no rows lost", before == after == 1, (before, after))
    ok("legacy row defaults to empty", relay2.connect(old).execute(
        "SELECT to_number FROM attempt").fetchone()[0] == "")

    print("5/6 a third-party body over Twilio's limit is still too-long")
    r5 = relay.submit("family_chat", "test.third", "x" * 1700, to=FAMILY, dedupe_disabled=True,
                      dedupe_extra="1700")
    ok("verdict is SEND", r5["verdict"] == "SEND", r5)
    ok("reason is too-long", r5["reason"] == "too-long", r5)

    print("6/6 dedupe still works with the new column")
    r6a = relay.submit("app", "test.dup", "the same body twice", to=OWNER, dedupe_extra="dup-1")
    r6b = relay.submit("app", "test.dup", "the same body twice", to=OWNER, dedupe_extra="dup-1")
    ok("first is SEND", r6a["verdict"] == "SEND", r6a)
    ok("second is DEDUPE", r6b["verdict"] == "DEDUPE", r6b)

    # ---- 7. FAMILY CHAT IS A SEPARATE SYSTEM (owner, 2026-10-18) -----------------------
    # "the family chat system is not part of the regular rate limits and is a completely
    # separate thing." So: family traffic is never cut to the owner's 320 reading ceiling,
    # EVEN WHEN THE RECIPIENT IS THE OWNER, and is never held by the owner's floor.
    print("7/9 family chat is a separate channel, even when the recipient is the owner")
    ok("is_separate_channel(family_chat)", relay.is_separate_channel("family_chat.owner_leg",
                                                                    "family_chat"))
    ok("is_separate_channel(app) is False", not relay.is_separate_channel("sms_service.send_message", "app"))
    ok("ceiling for family -> owner is the transport limit",
       relay.ceiling_for(OWNER, "family_chat.owner_leg", "family_chat") == relay.THIRD_PARTY_MAX,
       relay.ceiling_for(OWNER, "family_chat.owner_leg", "family_chat"))
    ok("ceiling for app -> owner is still 320",
       relay.ceiling_for(OWNER, "sms_service.send_message", "app") == relay.MAX_CHARS)

    longs = LONG.ljust(600, " ")          # over the owner ceiling, under the transport limit
    r7 = relay.submit("family_chat", "family_chat.owner_leg", longs, to=OWNER,
                      dedupe_disabled=True, dedupe_extra="fam-long")
    ok("a 600-char family message to the owner is SEND/ok, not too-long",
       r7["verdict"] == "SEND" and r7["reason"] != "too-long", r7)

    print("8/9 a delivery to the owner does not hold a family message (the floor)")
    # Plant a fresh delivered attempt to the owner so the floor has something to fire on.
    con3 = sqlite3.connect(db)
    con3.execute("INSERT INTO attempt (at, door, subsystem, body, body_hash, verdict,"
                 " verdict_reason, status, sid, sent_at, to_number) VALUES "
                 "(?,?,?,?,?,?,?,?,?,?,?)",
                 (relay._iso(relay._now()), "app", "app", "just texted him", "hfloor",
                  "SEND", "ok", "sent", "SMFLOOR", relay._iso(relay._now()), OWNER))
    con3.commit()
    con3.close()
    r8a = relay.submit("app", "sms_service.send_message", "an ordinary company text",
                       to=OWNER, dedupe_extra="floor-app")
    ok("the same text from the APP is FLOOR-held", r8a["verdict"] == "FLOOR", r8a)
    r8b = relay.submit("family_chat", "family_chat.owner_leg", "a relative's message",
                       to=OWNER, dedupe_disabled=True, dedupe_extra="floor-fam")
    ok("the family message is NOT floor-held", r8b["verdict"] == "SEND", r8b)

    print("9/9 the owner-facts are unchanged")
    ok("a 377-char app body to the owner is still too-long",
       relay.submit("app", "sms_service.send_message", LONG, to=OWNER,
                    dedupe_extra="owner-still").get("reason") == "too-long")

    print()
    if FAILED:
        print(f"{PASSED} passed, {len(FAILED)} FAILED: {', '.join(FAILED)}")
        return 1
    print(f"{PASSED} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
