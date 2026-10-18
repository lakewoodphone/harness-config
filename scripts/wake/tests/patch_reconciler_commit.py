#!/usr/bin/env python3
"""Commit each status update instead of holding the wake store's write lock across HTTP calls.

MEASURED 2026-10-18. `reconcile-sent-status.py` does:

    for r in rows:                       # up to 25 rows
        urlopen(...)                     # an HTTP call to Twilio, timeout 30
        if real != old and a.apply:
            conn.execute("UPDATE messages SET status=? WHERE sid=?", ...)   # opens implicit txn
    if a.apply:
        conn.commit()                    # only here, after the whole loop

Python's sqlite3 opens an implicit transaction on the first DML statement, so the store's WRITE LOCK
is held for the remainder of the loop -- i.e. across every remaining Twilio round-trip. Proven with a
controlled experiment (/root/_prove_lock_mechanism.py): a child that updates then sleeps leaves
BEGIN IMMEDIATE failing with `database is locked` for the whole sleep, and succeeding the instant it
commits.

WHY IT MATTERS: this script runs every 10 minutes against `~/.sms-inbox/inbox.db`, which is the same
store the dispatcher renews leases on. Three shifts (wake #1170, #1169, #1123) were killed on
2026-10-18 between 04:17 and 04:21 because a heartbeat could not renew its lease until the margin ran
out, with `wake: database error: database is locked` in the warning lines. A lock held for the
duration of 25 HTTP calls is exactly that shape.

Idempotent, parse-checked.
"""
import ast
import io
import sys

P = "/home/zabz/bin/reconcile-sent-status.py"

OLD = '''        if real != old and a.apply:
            conn.execute("UPDATE messages SET status=? WHERE sid=?", (real, sid))
            changed += 1'''

NEW = '''        if real != old and a.apply:
            conn.execute("UPDATE messages SET status=? WHERE sid=?", (real, sid))
            # COMMIT PER ROW. MEASURED 2026-10-18: the implicit transaction used to stay open until
            # after the loop, holding this store's write lock across every remaining HTTP call. The
            # same store carries the dispatcher's lease heartbeats, and a heartbeat that cannot renew
            # kills the shift -- three died at 04:17-04:21 with `database is locked`. A lock held for
            # the length of a network round-trip is not a database problem, it is an ordering problem.
            conn.commit()
            changed += 1'''

src = io.open(P, encoding="utf-8").read()
if "COMMIT PER ROW" in src:
    print("ALREADY-PATCHED: nothing written")
    sys.exit(0)
if src.count(OLD) != 1:
    print("REFUSED: anchor found %d times" % src.count(OLD))
    sys.exit(2)
out = src.replace(OLD, NEW, 1)
try:
    ast.parse(out)
except SyntaxError as exc:
    print("REFUSED: would not parse: %s" % exc)
    sys.exit(3)
io.open(P, "w", encoding="utf-8").write(out)
print("WROTE %s  %d -> %d chars" % (P, len(src), len(out)))
