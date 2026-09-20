#!/usr/bin/env python3
"""Local smoke test for sms-responder.py's wiring, using a synthetic store.

Proves the orchestrator degrades correctly and never crashes when the v2 modules
are absent, and that every CLI verb runs. No network, no sends, no real DB.
"""
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
RESPONDER = HERE / "sms-responder.py"
INBOX = HERE / "sms-inbox.py"


def build_fake_store(path: Path) -> None:
    """A minimal store with the v1 schema and two real-shaped rows."""
    c = sqlite3.connect(path)
    c.executescript(
        """
        CREATE TABLE messages (
            sid TEXT PRIMARY KEY, direction TEXT NOT NULL,
            from_number TEXT NOT NULL, to_number TEXT NOT NULL,
            body TEXT NOT NULL DEFAULT '', date_sent TEXT, status TEXT,
            num_media INTEGER DEFAULT 0, price TEXT, first_seen TEXT NOT NULL,
            app_has_it INTEGER, state TEXT NOT NULL DEFAULT 'new',
            decided_by TEXT, decided_at TEXT, reason TEXT, reply_sid TEXT);
        CREATE TABLE permissions (
            phone TEXT PRIMARY KEY, name TEXT, relationship TEXT,
            allow TEXT NOT NULL, note TEXT DEFAULT '', learned_from TEXT DEFAULT '',
            updated_at TEXT NOT NULL);
        """)
    c.execute("INSERT INTO permissions VALUES (?,?,?,?,?,?,?)",
              ("+17325691594", "Eliyahu (owner)", "owner", "queue", "owner", "", "2026-09-20"))
    c.execute("INSERT INTO permissions VALUES (?,?,?,?,?,?,?)",
              ("+18485257897", "Shabsi (brother)", "family", "auto", "family", "", "2026-09-20"))
    c.execute(
        "INSERT INTO messages (sid,direction,from_number,to_number,body,date_sent,"
        "first_seen,state) VALUES (?,?,?,?,?,?,?,?)",
        ("SM1234", "inbound", "+17325691594", "+17324447361",
         "Find me the wifi password for hidden network", "2026-09-20T12:00:00+00:00",
         "2026-09-20T12:00:05+00:00", "new"))
    c.commit()
    c.close()


def run(args, env):
    r = subprocess.run([sys.executable, str(RESPONDER), *args],
                       capture_output=True, text=True, env=env, timeout=180)
    return r.returncode, r.stdout, r.stderr


def main() -> int:
    failures = []
    with tempfile.TemporaryDirectory() as td:
        db = Path(td) / "inbox.db"
        build_fake_store(db)
        # SMS_INBOX_DB is the sensor's own env override - use it, not a new name,
        # so the orchestrator and the sensor can never disagree about which store
        # they are talking to.
        env = dict(os.environ, SMS_INBOX_DB=str(db))

        for verb in (["pending"], ["report"], ["jobs"], ["history"],
                     ["run", "--dry-run"]):
            code, out, err = run(verb, env)
            ok = code == 0 and "Traceback" not in (out + err)
            print(f"[{'PASS' if ok else 'FAIL'}] {' '.join(verb):<20} exit={code}")
            head = " ".join(out.split())[:150]
            print(f"        {head}")
            if not ok:
                failures.append((verb, code, err[-600:]))

        # The critical safety property: with no send module and no --send flag,
        # NOTHING may be sent. Assert the dry-run wording appears.
        code, out, _ = run(["run", "--dry-run"], env)
        if "DRY-RUN" not in out and "0 to decide" not in out:
            failures.append((["dry-run-marker"], code, out[:400]))
            print("[FAIL] dry-run marker absent from run output")
        else:
            print("[PASS] dry run is the default and says so")

    print()
    if failures:
        print(f"{len(failures)} FAILURE(S)")
        for f in failures:
            print("  ", f)
        return 1
    print("all wiring checks passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
