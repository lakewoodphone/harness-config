#!/usr/bin/env python3
"""FLAG SOURCE: the company database failed its own integrity check, or nobody ran the check.

THE SIGNAL
----------
`~/bin/db-integrity-check.py --json --write-status` runs one read-only `PRAGMA quick_check(1)` on
`personal-secretary-mvp/data/secretary.db` and writes `~/.db-integrity/status.json` with `ok`, `at`,
`result`, `error` and `seconds`.

WHY THIS SOURCE EXISTS (journal P167, verified 2026-09-30)
----------------------------------------------------------
The authority ran a corruption alarm whose only transport was `mail` -- and `command -v mail` finds
nothing on this host, nor `sendmail`. The finding's remaining route was one append to
`~/secretary-db-errors.log`, whose last line is dated 2026-09-10. A database-corruption alarm that
cannot reach a human is worse than no alarm, because the record shows it exists.

This source gives it the route every other finding in this system has: a ledger item.

TWO SIGNALS, deliberately:
  1. THE DATABASE IS NOT OK. High priority; the prompt says what to do first (stop writing, take a
     copy before anything else) and what NOT to do (never run a repair on the live file).
  2. THE CHECK HAS NOT RUN. `at` older than the ceiling means the alarm is dead, not the database
     healthy -- the exact confusion P167 was. This half raises Unreadable rather than filing, so it
     shows up as a FAILED source in `sources.log` instead of a flag that reads like a real finding.

PRIORITY  high when the database is not ok; normal when only the check is stale.

SUBJECTS  db-integrity:<result or not-run>   -- keyed to what was actually found, so a persistent
          fault re-files once and a *change* in the fault re-files immediately.

MUST NEVER
    - touch the database: it reads one pragma and its own two files;
    - treat "the check did not run" as "the database is fine". That is the defect it exists to end.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import _flag  # noqa: E402
from _flag import Finding, Unreadable  # noqa: E402

SOURCE = "db-integrity"
CHECKER = Path(os.environ.get("DB_INTEGRITY_CHECKER", str(Path.home() / "bin" / "db-integrity-check.py")))
STATUS = Path(os.environ.get("DB_INTEGRITY_STATUS", str(Path.home() / ".db-integrity" / "status.json")))
# The cron runs daily; 30 h means one missed run is a finding, which is the point.
MAX_AGE_HOURS = float(os.environ.get("DB_INTEGRITY_MAX_AGE_HOURS", "30"))
COOLDOWN_SECONDS = int(os.environ.get("DB_INTEGRITY_COOLDOWN", "21600"))


def _read_status() -> dict:
    """READ the checker's status file. NEVER re-run the check.

    Measured 2026-09-30, my own design error: the first version of this source ran the checker, and
    one `PRAGMA quick_check(1)` on the 14 GB database takes **752 seconds**. The sources loop runs
    every 15 minutes and wraps each source in `timeout 90`, so this source would have been killed at
    90 s on every single pass and logged `FAILED rc=124` forever -- a permanently red source, which
    is the alarm-fatigue failure journal P52 and P6 both record.

    The division of labour has to be: the cron runs the check and writes the file; this source reads
    the file and decides. If the file is missing, that is a real finding -- the alarm has no evidence
    -- and it is raised as Unreadable so it appears as a broken signal rather than a quiet pass.
    """
    if not STATUS.is_file():
        raise Unreadable("no status file at %s -- the daily check has never run, or was removed"
                         % STATUS)
    try:
        raw = STATUS.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not read %s: %s" % (STATUS, exc))
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("the status file is not JSON: %s" % exc)


def _run_checker():  # kept for --force, never used by the cron path
    if not CHECKER.is_file():
        raise Unreadable("the checker itself is missing at %s" % CHECKER)
    try:
        p = subprocess.run([sys.executable or "python3", str(CHECKER), "--json", "--write-status"],
                           capture_output=True, text=True, timeout=1800)
    except subprocess.TimeoutExpired:
        raise Unreadable("the checker did not finish within 1800 s")
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("could not run the checker: %s" % exc)
    raw = (p.stdout or "").strip()
    if not raw:
        raise Unreadable("the checker printed nothing (rc=%s, stderr=%s)"
                         % (p.returncode, (p.stderr or "").strip()[:200]))
    try:
        return json.loads(raw)
    except Exception as exc:  # noqa: BLE001
        raise Unreadable("the checker output is not JSON: %s" % exc)


def collect(args) -> list[Finding]:
    r = _run_checker() if getattr(args, "force", False) else _read_status()
    at = r.get("at") or ""
    try:
        when = datetime.strptime(at, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except Exception:  # noqa: BLE001
        raise Unreadable("the checker wrote no usable timestamp (at=%r)" % at)

    age_h = (datetime.now(timezone.utc) - when).total_seconds() / 3600.0
    if age_h > MAX_AGE_HOURS:
        # Not a finding about the database: a finding about the ALARM. Say it as a broken signal.
        raise Unreadable("the integrity check has not completed for %.1f h (ceiling %.0f h)"
                         % (age_h, MAX_AGE_HOURS))

    if r.get("ok"):
        return []

    result = (r.get("result") or r.get("error") or "unknown")[:400]
    prompt = (
        "THE COMPANY DATABASE FAILED ITS OWN INTEGRITY CHECK.\n\n"
        "    db      : %s\n"
        "    when    : %s\n"
        "    result  : %s\n"
        "    seconds : %s\n\n"
        "This is the database the whole company reads: 14 GB of SQLite at\n"
        "`/home/zabz/personal-secretary-mvp/data/secretary.db`. It is written by the API, the\n"
        "autopilot, the wake sources, the backups and cron at once.\n\n"
        "WHAT TO DO, in this order, and slowly:\n"
        "  1. Before anything else, copy the database AND its `-wal` and `-shm` files to a path on\n"
        "     another device. Do not move or delete the originals: a damaged SQLite is still the\n"
        "     only copy of the data.\n"
        "  2. Read the result above. `quick_check(1)` stops at the FIRST error, so it names one\n"
        "     thing, not all of them.\n"
        "  3. Do NOT run `.recover`, `VACUUM`, or any write against the live file. A repair on the\n"
        "     serving copy turns a readable database into an unreadable one.\n"
        "  4. Work on the COPY: `sqlite3 copy.db \".recover\" | sqlite3 rebuilt.db`, then\n"
        "     `PRAGMA integrity_check` on the rebuild, then compare row counts of the tables that\n"
        "     matter against the newest backup in `/home/zabz/secretary-backups/`.\n"
        "  5. Only then bring it back, with a written record of what was lost, and tell the owner\n"
        "     in plain language which rows are affected.\n\n"
        "If the result is a false positive, say so with the evidence (a second check, and the\n"
        "command that produced the clean answer) rather than repairing anything.\n\n"
        "Proof for whatever you do: `python3 ~/bin/db-integrity-check.py` and paste its first line."
    ) % (r.get("db"), at, result, r.get("seconds"))

    return [Finding(
        subject="db-integrity:%s" % ("error" if r.get("error") else "corrupt"),
        prompt=prompt,
        priority="high",
        kind="repair",
        context=json.dumps({k: r.get(k) for k in ("at", "db", "ok", "result", "error", "seconds",
                                                  "bytes")}),
        cooldown_seconds=COOLDOWN_SECONDS,
    )]


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
