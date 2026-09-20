#!/usr/bin/env python3
"""Re-classify the 11 rows resolved -> dismissed, with a real busy timeout.

WHY THIS REPLACES THE FIRST ATTEMPT: the first version called the CLI, which uses
`sqlite3.connect(path, timeout=20)`. Under the live API's write load that is too short, so
it sat in the CLI's 20 s wait while the DB was locked and only got through one row before the
ssh client was cut off at 300 s. My operating brief says exactly this: a `database is locked`
write is transient contention, and the fix is `timeout=180` plus `PRAGMA busy_timeout`, not
giving up. So this writes directly, replicating `_close()` step for step (commit the read
snapshot BEFORE the UPDATE, or the deferred read transaction cannot upgrade to a write and
SQLite returns SQLITE_BUSY immediately).

It reads the existing `resolution` text and writes it back VERBATIM, guarded by
`AND status='resolved'` so a concurrent writer cannot cause a clobber, and it proves
preservation by sha256 before/after.
"""
import datetime as dt
import hashlib
import sqlite3
import sys
import time

DB = "/home/zabz/personal-secretary-mvp/data/secretary.db"
IDS = [65, 72, 76, 83, 73, 82, 24, 92, 89, 95, 90]
PH = ",".join("?" * len(IDS))


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def write_row(con, rid: int, text: str, attempts: int = 6) -> bool:
    for n in range(1, attempts + 1):
        try:
            con.execute(
                "UPDATE owner_decision_queue SET status='dismissed', resolved_at=?, resolution=? "
                "WHERE id=? AND status='resolved'",
                (now(), text, rid),
            )
            con.commit()
            return True
        except sqlite3.OperationalError as exc:
            if "locked" in str(exc).lower() or "busy" in str(exc).lower():
                print("#%d: contended (attempt %d/%d): %s" % (rid, n, attempts, exc), flush=True)
                time.sleep(20)
                continue
            raise
    return False


con = sqlite3.connect(DB, timeout=180)
con.execute("PRAGMA busy_timeout=180000")
con.row_factory = sqlite3.Row

snap = {}
for r in con.execute(
    "SELECT id, status, resolution FROM owner_decision_queue WHERE id IN (%s)" % PH, IDS
):
    snap[r["id"]] = (r["status"], r["resolution"])
con.commit()  # close the read snapshot before any write

print("=== PRE-WRITE ===", flush=True)
for i in IDS:
    st, text = snap.get(i, ("MISSING", None))
    print("#%-3d %-9s len=%-5d sha=%s" % (i, st, len(text or ""), sha(text)[:16]), flush=True)

rows = []
for i in IDS:
    st, text = snap.get(i, ("MISSING", None))
    if st == "dismissed":
        rows.append((i, "already-dismissed", "n/a (unchanged)", sha(text)[:16], len(text or "")))
        print("#%-3d already dismissed, left untouched" % i, flush=True)
        continue
    if st != "resolved" or not (text or "").strip():
        rows.append((i, "UNEXPECTED:" + str(st), "REFUSED", sha(text)[:16], len(text or "")))
        print("#%-3d REFUSING: status=%r, text empty=%s" % (i, st, not (text or "").strip()), flush=True)
        continue
    ok = write_row(con, i, text)
    after = con.execute("SELECT status, resolution FROM owner_decision_queue WHERE id=?", (i,)).fetchone()
    con.commit()
    preserved = sha(after["resolution"]) == sha(text)
    verdict = "VERBATIM" if (ok and preserved and after["status"] == "dismissed") else "*** PROBLEM ***"
    rows.append((i, after["status"], verdict, sha(text)[:16], len(after["resolution"] or "")))
    print("#%-3d %s -> %s  %s  len=%d" % (i, st, after["status"], verdict, len(after["resolution"] or "")), flush=True)

con.close()

print("\n=== SUMMARY ===", flush=True)
bad = [r for r in rows if r[2] not in ("VERBATIM", "n/a (unchanged)")]
for r in rows:
    print("#%-3d %-18s %-16s sha=%s len=%d" % r, flush=True)
print("PROBLEMS: %s" % (bad if bad else "none"), flush=True)
