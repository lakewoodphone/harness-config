#!/usr/bin/env python3
"""The store: schema, and every write to it, for the AI text line.

One module owns the database so that no two parts of the system can disagree about
what a row means. Everything else reads through here or reads read-only.

The store is `~/.sms-inbox/inbox.db`, the same file `sms-inbox.py` (the sensor)
already reconciles from Twilio. Its env override is `SMS_INBOX_DB` and that is
honoured here too, so the sensor and this module can never be pointed at two
different files by accident.

Three tables matter:

  messages      the correspondence itself (owned by the sensor)
  permissions   the ledger: allow = auto | queue | never, per phone
  jobs          ONE ROW PER PROMISE - "I'll look into it" is not a sentence, it is
                a row with a state and a follow-through. This is what makes the
                system's promises sinkable. (audit finding B4)
  person        what we have learned about who someone is, so a later run does not
                have to ask a human again. (audit finding B8)

CLI
    python3 textstore.py ensure          # create/verify the schema
    python3 textstore.py doctor          # is the store coherent?  non-zero if not
    python3 textstore.py jobs            # what promises are open
"""
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
DB_PATH = Path(os.environ.get("SMS_INBOX_DB") or (HOME / ".sms-inbox" / "inbox.db"))

SCHEMA_VERSION = 2

# Additive only. Never DROP, never DELETE a row from this module: a state change is
# an UPDATE, so the record of what happened survives.
MIGRATIONS = [
    (
        "v2_jobs",
        """
        CREATE TABLE IF NOT EXISTS jobs (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            phone        TEXT NOT NULL,
            inbound_sid  TEXT,
            claim        TEXT NOT NULL,
            task         TEXT,
            answer       TEXT,
            state        TEXT NOT NULL DEFAULT 'open',
            attempts     INTEGER NOT NULL DEFAULT 0,
            evidence     TEXT,
            created_at   TEXT NOT NULL,
            due_at       TEXT,
            updated_at   TEXT NOT NULL
        );
        """,
    ),
    ("v2_jobs_idx", "CREATE INDEX IF NOT EXISTS idx_jobs_state ON jobs(state, created_at);"),
    ("v2_jobs_phone", "CREATE INDEX IF NOT EXISTS idx_jobs_phone ON jobs(phone, state);"),
    (
        "v2_person",
        """
        CREATE TABLE IF NOT EXISTS person (
            phone         TEXT PRIMARY KEY,
            name          TEXT,
            relationship  TEXT,
            source        TEXT,
            confidence    REAL,
            first_seen    TEXT,
            last_seen     TEXT,
            updated_at    TEXT NOT NULL
        );
        """,
    ),
    ("v2_meta", "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);"),
]

# Columns a caller may set on a job. A whitelist, not a string-interpolated dict:
# job_set builds SQL from its keys.
JOB_FIELDS = ("state", "claim", "task", "answer", "evidence", "due_at",
              "attempts", "inbound_sid", "phone")
JOB_STATES = ("open", "running", "done", "blocked", "cancelled")


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect(path=None) -> sqlite3.Connection:
    """Open the store, creating its directory if needed.

    WAL + a 20 s busy timeout: the cron runs every five minutes and a slow run must
    wait for a lock rather than fail. `database is locked` returning a 500 to
    Twilio is exactly how 77 inbound texts were lost (audit B1/H536).
    """
    p = Path(path) if path else DB_PATH
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=20000")
        conn.execute("PRAGMA synchronous=NORMAL")
    except sqlite3.Error:
        pass
    return conn


def ensure_schema(conn: sqlite3.Connection) -> dict:
    """Idempotently bring the store up to date. Safe to run concurrently.

    Returns what it did, so a caller can prove whether a migration happened rather
    than assume it did.
    """
    created, existing = [], []
    for name, sql in MIGRATIONS:
        before = _table_names(conn)
        try:
            conn.executescript(sql)
            conn.commit()
        except sqlite3.OperationalError as exc:
            # Two cron runs racing on CREATE TABLE IF NOT EXISTS is normal; anything
            # else is not, and saying nothing about it is how a migration "succeeds"
            # without having run.
            if "already exists" not in str(exc).lower():
                raise
        after = _table_names(conn)
        (created if after - before else existing).append(name)
    try:
        conn.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                     (str(SCHEMA_VERSION),))
        conn.commit()
    except sqlite3.Error:
        pass
    return {"created": created, "existing": existing, "version": SCHEMA_VERSION}


def _table_names(conn: sqlite3.Connection) -> set:
    try:
        return {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    except sqlite3.Error:
        return set()


# --------------------------------------------------------------------------- #
# person
# --------------------------------------------------------------------------- #
def upsert_person(conn, phone: str, name: str | None = None, relationship: str | None = None,
                  source: str | None = None, confidence: float | None = None) -> dict:
    """Remember who someone is, permanently.

    Only overwrites a field when a value is actually supplied: a later run that
    learns the name must not blank out a relationship learned earlier.
    """
    if not phone:
        raise ValueError("phone is required")
    ensure_schema(conn)
    row = conn.execute("SELECT * FROM person WHERE phone=?", (phone,)).fetchone()
    ts = now()
    if row is None:
        conn.execute(
            "INSERT INTO person(phone,name,relationship,source,confidence,first_seen,"
            "last_seen,updated_at) VALUES(?,?,?,?,?,?,?,?)",
            (phone, name, relationship, source, confidence, ts, ts, ts))
    else:
        conn.execute(
            "UPDATE person SET name=COALESCE(?,name), relationship=COALESCE(?,relationship),"
            " source=COALESCE(?,source), confidence=COALESCE(?,confidence),"
            " last_seen=?, updated_at=? WHERE phone=?",
            (name, relationship, source, confidence, ts, ts, phone))
    conn.commit()
    got = conn.execute("SELECT * FROM person WHERE phone=?", (phone,)).fetchone()
    return dict(got) if got else {}


def get_person(conn, phone: str) -> dict | None:
    try:
        row = conn.execute(
            "SELECT * FROM person WHERE substr(replace(replace(phone,'+',''),'-',''),-10)"
            "=substr(?, -10)", (phone or "",)).fetchone()
        return dict(row) if row else None
    except sqlite3.Error:
        return None


# --------------------------------------------------------------------------- #
# jobs - one row per promise
# --------------------------------------------------------------------------- #
def open_job(conn, phone: str, inbound_sid: str | None, claim: str,
             task: str | None = None, due_at: str | None = None) -> int:
    ensure_schema(conn)
    ts = now()
    cur = conn.execute(
        "INSERT INTO jobs(phone,inbound_sid,claim,task,state,attempts,created_at,"
        "due_at,updated_at) VALUES(?,?,?,?,'open',0,?,?,?)",
        (phone, inbound_sid, claim[:500], (task or "")[:2000], ts, due_at, ts))
    conn.commit()
    return int(cur.lastrowid)


def jobs_open(conn, phone: str | None = None) -> list:
    ensure_schema(conn)
    if phone:
        tail = "".join(ch for ch in phone if ch.isdigit())[-10:]
        return conn.execute(
            "SELECT * FROM jobs WHERE state IN ('open','running') "
            "AND substr(replace(replace(phone,'+',''),'-',''),-10)=? "
            "ORDER BY created_at ASC", (tail,)).fetchall()
    return conn.execute(
        "SELECT * FROM jobs WHERE state IN ('open','running') ORDER BY created_at ASC").fetchall()


def job_get(conn, job_id: int):
    ensure_schema(conn)
    return conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()


def job_set(conn, job_id: int, **fields) -> bool:
    """Update a job. Only whitelisted columns, only known states."""
    bad = set(fields) - set(JOB_FIELDS)
    if bad:
        raise ValueError(f"cannot set job field(s): {sorted(bad)}")
    if "state" in fields and fields["state"] not in JOB_STATES:
        raise ValueError(f"unknown job state {fields['state']!r}; known: {JOB_STATES}")
    if not fields:
        return False
    ensure_schema(conn)
    fields["updated_at"] = now()
    # Iterating JOB_FIELDS rather than the caller's dict keeps the SQL fixed.
    sets, vals = [], []
    for k in JOB_FIELDS + ("updated_at",):
        if k in fields:
            sets.append(f"{k}=?")
            vals.append(fields[k])
    vals.append(job_id)
    conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id=?", vals)
    conn.commit()
    return True


def job_sweep(conn, *, lease_minutes: int = 30, max_attempts: int = 3, now_ts: str | None = None) -> dict:
    """Stop a promise being silently lost when a run dies mid-job.

    A job left `running` past its lease goes back to `open` with an incremented
    attempt count, or to `blocked` once it has tried too many times. Without this,
    a killed process means a person waiting forever on a promise the system still
    believes it is keeping.
    """
    ensure_schema(conn)
    ts = now_ts or now()
    cutoff = (datetime.fromisoformat(ts.replace("Z", "+00:00"))
              - timedelta(minutes=lease_minutes)).isoformat(timespec="seconds")
    requeued, blocked = [], []
    for row in conn.execute(
            "SELECT id, attempts FROM jobs WHERE state='running' AND updated_at < ?",
            (cutoff,)).fetchall():
        attempts = int(row["attempts"] or 0) + 1
        if attempts >= max_attempts:
            job_set(conn, row["id"], state="blocked", attempts=attempts,
                    evidence=f"gave up after {attempts} attempts (swept {ts})")
            blocked.append(row["id"])
        else:
            job_set(conn, row["id"], state="open", attempts=attempts)
            requeued.append(row["id"])
    return {"requeued": requeued, "blocked": blocked, "at": ts}


# --------------------------------------------------------------------------- #
def doctor(conn) -> dict:
    """Is the store coherent? Returns findings; exits non-zero on a real problem."""
    ensure_schema(conn)
    out = {"schema_version": SCHEMA_VERSION, "tables": sorted(_table_names(conn)),
           "problems": [], "counts": {}, "notes": []}
    for t in ("messages", "permissions", "jobs", "person"):
        try:
            out["counts"][t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        except sqlite3.Error:
            out["counts"][t] = None
            # `messages` and `permissions` belong to the SENSOR, not to this module.
            # Their absence is a note about a fresh store, not a fault: reporting it
            # as a problem would make `doctor` red on a store that is simply new.
            if t in ("messages", "permissions"):
                out["notes"].append(f"{t} absent - the sensor has not created it yet")

    # A job pointing at a phone we have never corresponded with is a bug, not a
    # curiosity: it means a promise was filed against a typo'd number.
    try:
        orphans = conn.execute(
            """SELECT j.id, j.phone FROM jobs j
               WHERE j.state IN ('open','running')
                 AND NOT EXISTS (
                   SELECT 1 FROM messages m
                   WHERE substr(replace(replace(m.from_number,'+',''),'-',''),-10)
                       = substr(replace(replace(j.phone,'+',''),'-',''),-10))"""
        ).fetchall()
        for r in orphans:
            out["problems"].append(f"open job #{r['id']} for {r['phone']} has no message from them")
    except sqlite3.Error as exc:
        # No `messages` table yet means a brand-new store, not a fault - the sensor
        # creates that table. Anything else is worth saying out loud.
        if "no such table" in str(exc).lower():
            out["notes"].append("orphan check skipped: no messages table yet")
        else:
            out["problems"].append(f"orphan check failed: {exc}")

    # A job stuck in `running` past its lease is work that has silently stopped.
    stale = job_sweep(conn, lease_minutes=30)
    out["swept"] = stale
    blocked_jobs = conn.execute("SELECT COUNT(*) FROM jobs WHERE state='blocked'").fetchone()[0]
    out["counts"]["jobs_blocked"] = blocked_jobs
    return out


def cmd_ensure(args) -> int:
    conn = connect()
    res = ensure_schema(conn)
    print(f"store      {DB_PATH}")
    print(f"version    {res['version']}")
    print(f"created    {res['created'] or '(nothing new)'}")
    print(f"existing   {res['existing'] or '(none)'}")
    return 0


def cmd_doctor(args) -> int:
    conn = connect()
    out = doctor(conn)
    print(f"store      {DB_PATH}")
    print(f"version    {out['schema_version']}")
    print(f"counts     {out['counts']}")
    if out.get("swept"):
        s = out["swept"]
        if s["requeued"] or s["blocked"]:
            print(f"swept      requeued={s['requeued']} blocked={s['blocked']}")
    if out["problems"]:
        print(f"PROBLEMS ({len(out['problems'])}):")
        for p in out["problems"]:
            print(f"  - {p}")
        return 1
    print("no problems found")
    return 0


def cmd_jobs(args) -> int:
    conn = connect()
    rows = jobs_open(conn)
    print(f"{len(rows)} open job(s)")
    for r in rows:
        print("  #%-5s %-16s %-8s attempts=%s  %s"
              % (r["id"], r["phone"], r["state"], r["attempts"], (r["claim"] or "")[:60]))
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("ensure").set_defaults(func=cmd_ensure)
    sub.add_parser("doctor").set_defaults(func=cmd_doctor)
    sub.add_parser("jobs").set_defaults(func=cmd_jobs)
    args = p.parse_args()
    if not getattr(args, "func", None):
        args = p.parse_args(["doctor"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
