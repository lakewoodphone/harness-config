#!/usr/bin/env python3
"""DB INTEGRITY CHECK -- the corruption alarm had no transport, so it could never alert anyone.

WHY THIS EXISTS (journal P167, verified 2026-09-30)
---------------------------------------------------
The authority has run this cron line since July:

    17 4 * * * out=$(sqlite3 ... "PRAGMA quick_check;" 2>&1); case "$out" in
      ok) ;; *) printf "%s\\n" "$out" | mail -s "SECRETARY DB CORRUPTION DETECTED" root;
                 echo "DB corruption detected at $(date)" >> ~/secretary-db-errors.log ;;
    esac

Measured today: `command -v mail` -> nothing, `command -v sendmail` -> nothing. **There is no mail
transport on this host.** So the only route a corruption finding had to a human was a line in
`~/secretary-db-errors.log`, which nothing reads -- and that file's last entry is 2026-09-10 23:45,
twenty days ago, from a period when it *did* detect something.

So the check has three defects at once, and this file fixes all three:
  1. its alarm could never leave the machine      -> a status file plus a wake source
  2. nothing watched whether the check itself ran -> the status carries `at`, and the source
     raises Unreadable when it is more than a day stale, so a dead check is not a healthy check
  3. it ran `PRAGMA quick_check` on a 14 GB database inside a cron `case` -> bounded here, with
     `quick_check(1)` (stop at the first error), a read-only URI so it takes no write lock, and a
     hard timeout that reports rather than hangs.

READ-ONLY. It opens the database with `mode=ro`, runs one pragma, and writes only its own two files.
It never repairs anything: repairing a corrupt SQLite is a deliberate, backed-up, owner-aware act.

EXIT 0 the database answered `ok`; 1 it did not; 2 the check could not be run at all.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

DB = Path(os.environ.get("SECRETARY_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db"))
STATE_DIR = Path.home() / ".db-integrity"
STATUS = STATE_DIR / "status.json"
LOG = STATE_DIR / "check.log"
TIMEOUT_S = float(os.environ.get("DB_INTEGRITY_TIMEOUT", "600"))


def check() -> dict:
    at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"at": at, "db": str(DB), "ok": None, "result": None, "error": None, "seconds": None}
    if not DB.exists():
        out["ok"] = False
        out["error"] = "no database at %s" % DB
        return out
    out["bytes"] = DB.stat().st_size
    started = time.time()
    try:
        con = sqlite3.connect(DB.resolve().as_uri() + "?mode=ro", uri=True, timeout=TIMEOUT_S)
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = "could not open read-only: %s" % exc
        return out
    try:
        con.execute("PRAGMA busy_timeout = %d" % int(TIMEOUT_S * 1000))
        # quick_check(1) stops at the first error: the full check on 14 GB has been measured to
        # take minutes, and one named error is what a human needs to start.
        row = con.execute("PRAGMA quick_check(1)").fetchone()
        out["result"] = (row[0] if row else "") or ""
        out["ok"] = out["result"].strip().lower() == "ok"
    except Exception as exc:  # noqa: BLE001
        out["ok"] = False
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    finally:
        try:
            con.close()
        except Exception:  # noqa: BLE001
            pass
    out["seconds"] = round(time.time() - started, 1)
    return out


def render(r: dict) -> str:
    if r["ok"]:
        return "ok - %s answered 'ok' in %ss (%s bytes)" % (r["db"], r["seconds"],
                                                            r.get("bytes", "?"))
    if r["error"]:
        return "FAILED TO CHECK - %s" % r["error"]
    return "CORRUPTION - %s answered %r" % (r["db"], (r.get("result") or "")[:300])


def selftest() -> int:
    """Prove the detector fires on a database that is actually damaged, and stays quiet on a good one."""
    import tempfile
    problems = []
    good = Path(tempfile.mkdtemp()) / "good.db"
    con = sqlite3.connect(str(good))
    con.execute("CREATE TABLE t (a TEXT)")
    con.execute("INSERT INTO t VALUES ('x')")
    con.commit()
    con.close()

    global DB
    keep = DB
    DB = good
    r = check()
    if not r["ok"]:
        problems.append("a healthy database was reported corrupt: %r" % r)
    DB = keep

    # A real corruption, made with the documented escape hatch: overwrite half the file with zeros.
    bad = Path(tempfile.mkdtemp()) / "bad.db"
    con = sqlite3.connect(str(bad))
    con.execute("CREATE TABLE t (a TEXT)")
    for i in range(2000):
        con.execute("INSERT INTO t VALUES (?)", ("x" * 200,))
    con.commit()
    con.close()
    raw = bytearray(bad.read_bytes())
    for i in range(len(raw) // 2, len(raw)):
        raw[i] = 0
    bad.write_bytes(bytes(raw))
    DB = bad
    r2 = check()
    if r2["ok"]:
        problems.append("a zeroed database was reported healthy: %r" % r2)
    DB = keep

    if problems:
        print("SELFTEST FAILED")
        for p in problems:
            print("  - " + p)
        return 1
    print("SELFTEST OK (healthy -> ok, zeroed -> %s)" % (r2.get("result") or r2.get("error"))[:80])
    return 0


def main(argv: list[str]) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--write-status", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    a = ap.parse_args(argv)
    if a.selftest:
        return selftest()

    r = check()
    print(json.dumps(r, indent=1) if a.json else render(r))
    if a.write_status:
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = STATUS.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(r, indent=1) + "\n", encoding="utf-8")
            tmp.replace(STATUS)
            with LOG.open("a", encoding="utf-8") as fh:
                fh.write("%s  %s\n" % (r["at"], render(r)))
        except Exception as exc:  # noqa: BLE001
            print("WARN: could not write %s: %s" % (STATUS, exc), file=sys.stderr)
    return 0 if r["ok"] else (2 if r["error"] else 1)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
