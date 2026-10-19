#!/usr/bin/env python3
"""two-ledgers.py - which store holds the CFO questions, and how big is the union?

`sms_log` in the authority has 4,283 rows and holds NONE of the CFO questions he answered. The AI
line writes to its own store under `~/.sms-inbox`. If that is true, every figure measured from
`sms_log` alone - the replay, the conformance census, "482 texts reached him" - omits the single
largest class of complaint.

This counts both stores and looks for the ask bodies in each.
"""
import sqlite3

OWNER_DIGITS = "18483897895"
STORES = [("authority sms_log", "/root/authority.db", "sms_log"),
          ("sms-inbox", "/root/.sms-inbox/inbox.db", None)]

for label, path, table in STORES:
    print("== %s" % label)
    try:
        c = sqlite3.connect("file:%s?mode=ro" % path, uri=True)
    except Exception as exc:                                   # noqa: BLE001
        print("   cannot open: %s" % exc)
        continue
    try:
        names = [r[0] for r in c.execute(
            "select name from sqlite_master where type='table'")]
        print("   tables: %s" % ", ".join(names[:12]))
        # find any table with a body-ish column and a direction-ish column
        for t in names:
            cols = [r[1] for r in c.execute("pragma table_info(%s)" % t)]
            has_body = any(x in cols for x in ("body", "message", "text"))
            if not has_body:
                continue
            n = c.execute("select count(*) from %s" % t).fetchone()[0]
            if n == 0:
                continue
            print("   %-18s rows=%-6d cols=%s" % (t, n, cols[:8]))
            # does it hold an ask?
            bcol = next(x for x in ("body", "message", "text") if x in cols)
            try:
                hits = c.execute(
                    "select count(*) from %s where instr(coalesce(%s,''),'CFO [ask-') > 0"
                    % (t, bcol)).fetchone()[0]
                print("        rows containing 'CFO [ask-': %d" % hits)
            except Exception:                                  # noqa: BLE001
                pass
    finally:
        c.close()
    print()
