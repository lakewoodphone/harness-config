#!/usr/bin/env python3
"""sid-dedupe-regardless-of-state.py - one text is one turn, answered or not.

`owner_text.record_outbound` already has the right idea and the right comment: "One message, one
turn. Measured 2026-10-02: a single reminder opened rows #39 and #40 with the SAME sid ... so the
owner's reply would have closed one row and re-shut the channel."

But the guard only looks at turns that are still OPEN:

    SELECT id FROM owner_text_turn WHERE answered_at IS NULL AND sid = ?

So the sequence "record the send -> he answers, row closed -> the same send is recorded again"
finds nothing and inserts a SECOND row for the same sid. Measured over the 151-turn labelled set:
**29 turns share a sid with another row, and 19 of the 20 `owner_sms_reply` turns are doubled.**
Two rows for one text means one reply closes one of them, and the other keeps the channel shut - the
exact failure the guard was written to prevent.

A SID IDENTIFIES A TEXT and is unique per message, so the identity check does not depend on whether
the turn is still open. The BODY check keeps the open-only scope, because the same body is
legitimately sent again later and must be able to open a new turn.
"""
from __future__ import annotations

import io
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

PATH = Path(sys.argv[1] if len(sys.argv) > 1 else "/opt/company/app/owner_text.py")

OLD = '''        if sid:
            dup = conn.execute(
                "SELECT id FROM owner_text_turn"
                " WHERE answered_at IS NULL AND sid = ?"
                " ORDER BY id DESC LIMIT 1",
                (str(sid),),
            ).fetchone()'''

NEW = '''        if sid:
            # A SID IDENTIFIES A TEXT; answered-or-not is not part of its identity. Measured over
            # the 151-turn labelled set 2026-10-19: 29 turns share a sid, and 19 of the 20
            # `owner_sms_reply` turns are doubled - because a send recorded again AFTER his reply
            # found nothing (the previous row was answered) and opened a second turn. One reply
            # then closes one row and the other keeps the channel shut, which is the failure this
            # guard exists for. The body branch below stays open-only on purpose: the same body is
            # legitimately sent again later and must be able to open a new turn.
            dup = conn.execute(
                "SELECT id FROM owner_text_turn"
                " WHERE sid = ?"
                " ORDER BY id DESC LIMIT 1",
                (str(sid),),
            ).fetchone()'''

text = PATH.read_text(encoding="utf-8")
if NEW in text:
    print("OK    already applied")
    raise SystemExit(0)
if text.count(OLD) != 1:
    print("FAIL  anchor found %d times" % text.count(OLD))
    raise SystemExit(1)
out = text.replace(OLD, NEW, 1)
import ast
ast.parse(out)
if "--apply" not in sys.argv:
    print("DRY   would dedupe on sid regardless of answered state")
    raise SystemExit(0)
stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
shutil.copy2(PATH, PATH.with_suffix(PATH.suffix + ".bak-siddup-" + stamp))
tmp = PATH.with_suffix(PATH.suffix + ".new")
tmp.write_text(out, encoding="utf-8")
tmp.replace(PATH)
print("APPLIED %s" % PATH)
