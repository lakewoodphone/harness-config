#!/usr/bin/env python3
"""Prove that an uncommitted UPDATE holds the write lock across non-database work.

This is the mechanism suspected in reconcile-sent-status.py: it issues `UPDATE messages` inside a
loop that makes an HTTP request per row, and commits once after the loop. Python's sqlite3 begins an
implicit transaction on the first DML statement and does not end it until commit, so the store's
write lock is held for the whole loop.

The experiment uses a throwaway database, a child process that updates then sleeps WITHOUT touching
the database, and a second process that tries BEGIN IMMEDIATE with a short busy timeout. If the lock
is really held during the sleep, the second process fails with "database is locked".
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
import textwrap

d = tempfile.mkdtemp(prefix="lockproof-")
db = os.path.join(d, "t.db")

c = sqlite3.connect(db)
c.executescript("PRAGMA journal_mode=WAL; CREATE TABLE t(id INTEGER PRIMARY KEY, s TEXT);")
c.execute("INSERT INTO t VALUES (1,'old')")
c.commit()
c.close()

# Child: implicit transaction stays open across a sleep that does no database work.
child = textwrap.dedent("""
    import sqlite3, sys, time
    c = sqlite3.connect(sys.argv[1], timeout=0.2)
    c.execute("UPDATE t SET s='new' WHERE id=1")   # opens the implicit transaction
    time.sleep(4)                                   # the "HTTP call"
    c.commit()
""")
holder = subprocess.Popen([sys.executable, "-c", child, db])
try:
    import time as _t
    _t.sleep(1.0)                                   # let the child open its transaction

    probe = sqlite3.connect(db, timeout=0.5)
    probe.execute("PRAGMA busy_timeout=500")
    try:
        probe.execute("BEGIN IMMEDIATE")
        probe.execute("ROLLBACK")
        print("RESULT: the write lock was FREE during the sleep  -> mechanism NOT confirmed")
        ok = False
    except sqlite3.OperationalError as exc:
        print("RESULT: BEGIN IMMEDIATE failed while the child slept: %s" % exc)
        ok = "locked" in str(exc).lower()
    probe.close()
finally:
    holder.wait(timeout=15)

# And after the child commits, the lock is free again.
after = sqlite3.connect(db, timeout=0.5)
after.execute("PRAGMA busy_timeout=500")
after.execute("BEGIN IMMEDIATE")
after.execute("ROLLBACK")
after.close()
print("RESULT: after the child committed, BEGIN IMMEDIATE succeeds immediately  -> lock released")

print("\n%s  (throwaway db at %s)" % ("CONFIRMED: uncommitted UPDATE holds the write lock across "
                                      "non-database work" if ok else "NOT CONFIRMED", db))
sys.exit(0 if ok else 1)
