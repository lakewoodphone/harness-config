#!/usr/bin/env python3
"""security-selftest — does the whole security stack still work when composed?

Every component has its own test. This one runs the components TOGETHER against a throwaway record and
asserts the composed behaviour, which is the thing that actually breaks when someone edits one piece.

Cases:
  1. shop door, no credential, building expected empty  -> rule ESCALATE 3, agent ALARM/ESCALATE, level >= 3
  2. shop door + credential 3 s later                   -> rule NO_ALARM, level 0, and an entry_event row with a subject
  3. door with a recorder gap inside the window         -> ESCALATE 2, and the reason names the gap
  4. credential with no door                            -> NO_ALARM level 0
  5. the promotion gate refuses an unlearning proposal   -> exit 3
  6. the live record's health check passes               -> exit 0

Exit: 0 all cases pass, 1 a case failed, 2 could not run.
The throwaway database is deleted afterwards unless --keep.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile

VENV = "/opt/company/.venv/bin/python"
SCRIPTS = {"sentinel": "/root/security-sentinel.py", "agent": "/root/security-agent.py",
           "health": "/root/security-health.py", "propose": "/root/security-propose.py",
           "label": "/root/security-label.py", "scorecard": "/root/security-scorecard.py"}
SCHEMA = "/root/security-record-v1.sql"


def run(args: list[str], timeout: int = 180) -> subprocess.CompletedProcess:
    return subprocess.run(args, capture_output=True, text=True, timeout=timeout)


def sql(db: str, statement: str) -> list[tuple]:
    conn = sqlite3.connect(db, timeout=10.0, isolation_level=None)
    try:
        return list(conn.execute(statement))
    finally:
        conn.close()


def insert_event(db: str, ident: str, minutes_ago: int, entity: str, new_state: str,
                 raw: str | None = None, gap: int = 0) -> None:
    offset = f"-{minutes_ago} minutes"
    raw_sql = "NULL" if raw is None else "'" + raw.replace("'", "''") + "'"
    sql(db, f"INSERT INTO security_event (id, occurred_at, entity_id, new_state, raw, recorder_gap, "
            f"build_sha, created_at) VALUES ('{ident}', strftime('%Y-%m-%dT%H:%M:%SZ','now','{offset}'), "
            f"'{entity}', '{new_state}', {raw_sql}, {gap}, 'selftest', datetime('now'))")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-llm", action="store_true", help="skip the agent case (no model call)")
    ap.add_argument("--keep", action="store_true")
    args = ap.parse_args()

    workdir = tempfile.mkdtemp(prefix="sec-selftest-")
    db = os.path.join(workdir, "record.db")
    cursor = os.path.join(workdir, "cursor.txt")
    for path, need in ((SCRIPTS["sentinel"], "sentinel"), (SCHEMA, "schema")):
        if not os.path.exists(path):
            print(f"FATAL: missing {need} at {path}")
            return 2
    # build the throwaway record by EXECUTING the schema; writing the .sql text into the file produces
    # "file is not a database", which is what the first version did
    with open(SCHEMA) as fh:
        schema_text = fh.read()
    conn = sqlite3.connect(db)
    try:
        conn.executescript(schema_text)
    finally:
        conn.close()
    with open(cursor, "w") as fh:
        fh.write("0")

    results: list[tuple[str, bool, str]] = []

    def case(name: str, ok: bool, detail: str) -> None:
        results.append((name, ok, detail))
        print(f"{'PASS' if ok else 'FAIL'}  {name:52s} {detail}")

    # ---- case 1: unbadged door, building empty
    insert_event(db, "c1a", 10, "binary_sensor.phoenix_control_room_interior_door_contact", "on")
    r = run([VENV, SCRIPTS["sentinel"], "--once", "--no-seed", "--db", db, "--cursor", cursor, "--settle", "0"])
    rows = sql(db, "SELECT decision, avs_level, reason_one_line FROM security_decision "
                   "WHERE decided_by='fallback:shadow' ORDER BY created_at DESC LIMIT 1")
    ok = bool(rows) and rows[0][1] >= 3
    case("1. unbadged door while empty -> rule level >= 3", ok, f"{rows[0][0] if rows else 'none'} avs={rows[0][1] if rows else '-'}")

    # ---- case 2: door explained by a credential 3 s later
    insert_event(db, "c2a", 9, "binary_sensor.phoenix_control_room_exterior_door_contact", "on")
    insert_event(db, "c2b", 9, "event.phoenix.valid_pin", "received",
                 raw=json.dumps({"event_type": "phoenix.valid_pin",
                                 "data": {"pin_name": "Eliyahu", "door_name": "strike"}}))
    # the credential must be 3 s AFTER the door, so shift it explicitly
    sql(db, "UPDATE security_event SET occurred_at = strftime('%Y-%m-%dT%H:%M:%SZ','now','-9 minutes','+3 seconds') "
            "WHERE id='c2b'")
    run([VENV, SCRIPTS["sentinel"], "--once", "--no-seed", "--db", db, "--cursor", cursor, "--settle", "0"])
    rows = sql(db, "SELECT decision, avs_level, reason_one_line FROM security_decision "
                   "WHERE decided_by='fallback:shadow' AND rule_id LIKE 'R_DOOR+CRED%' ORDER BY created_at DESC LIMIT 1")
    entry = sql(db, "SELECT subject_id, confidence FROM entry_event ORDER BY id DESC LIMIT 1")
    ok = bool(rows) and rows[0][0] == "NO_ALARM" and bool(entry) and entry[0][0] == "owner"
    case("2. credentialed door -> NO_ALARM + named entry_event", ok,
         f"{rows[0][0] if rows else 'none'} avs={rows[0][1] if rows else '-'} subject={entry[0][0] if entry else '-'}")

    # ---- case 3: a gap inside the window must beat everything
    insert_event(db, "c3a", 8, "binary_sensor.phoenix_control_room_interior_door_contact", "on")
    insert_event(db, "c3b", 8, "security.listener", "reconnect after OSError", gap=1)
    run([VENV, SCRIPTS["sentinel"], "--once", "--no-seed", "--db", db, "--cursor", cursor, "--settle", "0"])
    rows = sql(db, "SELECT decision, avs_level, reason_one_line FROM security_decision "
                   "WHERE rule_id LIKE 'R_GAP%' ORDER BY created_at DESC LIMIT 1")
    ok = bool(rows) and rows[0][0] == "ESCALATE" and rows[0][1] == 2 and "gap" in rows[0][2]
    case("3. recorder gap -> ESCALATE 2 naming the gap", ok,
         f"{rows[0][0] if rows else 'none'} avs={rows[0][1] if rows else '-'}")

    # ---- case 4: a credential with no door is recorded, not alarming
    insert_event(db, "c4a", 7, "event.esphome.access_control_keypad_entry", "received",
                 raw=json.dumps({"event_type": "esphome.access_control_keypad_entry",
                                 "data": {"door_name": "strike"}}))
    before = sql(db, "SELECT COUNT(*) FROM security_decision")[0][0]
    run([VENV, SCRIPTS["sentinel"], "--once", "--no-seed", "--db", db, "--cursor", cursor, "--settle", "0"])
    rows = sql(db, "SELECT decision, avs_level FROM security_decision ORDER BY created_at DESC LIMIT 1")
    ok = rows[0][0] == "NO_ALARM" and rows[0][1] == 0
    case("4. credential with no door -> NO_ALARM level 0", ok, f"{rows[0][0]} avs={rows[0][1]}")

    # ---- case 5: the agent, on the unbadged episode
    if args.no_llm:
        print("SKIP  5. agent verdict                                     (--no-llm)")
    else:
        rr = run([VENV, SCRIPTS["agent"], "--once", "--db", db], timeout=240)
        rows = sql(db, "SELECT decision, avs_level, json_extract(considered,'$.injection_suspected') "
                       "FROM security_decision WHERE decided_by LIKE 'agent%' ORDER BY created_at LIMIT 1")
        ok = bool(rows) and rows[0][0] in ("ALARM", "ESCALATE")
        case("5. agent judges the unbadged episode", ok,
             f"{rows[0][0] if rows else 'none'} avs={rows[0][1] if rows else '-'}")

    # ---- case 6: the promotion gate refuses the unlearning rule
    r = run([VENV, SCRIPTS["propose"], "--label", "selftest: unlearning rule",
             "--param", "treat_missing_credential_as_benign=true", "--signal", "credential"], timeout=120)
    ok = r.returncode == 3 and "SYN1" in r.stdout
    case("6. gate refuses the unlearning rule, names SYN1", ok, f"exit={r.returncode}")

    # ---- case 7: live health
    r = run([VENV, SCRIPTS["health"]], timeout=120)
    ok = r.returncode == 0
    case("7. live security-health passes", ok, f"exit={r.returncode}")

    failed = [n for n, ok_, _ in results if not ok_]
    print(f"\n{len(results) - len(failed)}/{len(results)} cases passed")
    if failed:
        print("failed: " + ", ".join(failed))
    if args.keep:
        print(f"kept: {workdir}")
    else:
        shutil.rmtree(workdir, ignore_errors=True)
    return 0 if not failed else 1


if __name__ == "__main__":
    raise SystemExit(main())
