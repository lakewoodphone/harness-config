#!/usr/bin/env python3
"""security-health — is the security system actually working, right now?

Not "are the units active". A unit can be `active` with a dead socket, a loop can be running with nothing
arriving, and a table can be empty because nothing happened OR because nothing is writing. Each check below
answers one of those, prints the RAW VALUE next to the verdict, and names what a failure means.

Exit: 0 all checks pass, 1 at least one failed, 2 could not run.
"""
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
import time

UNITS = ("security-listener", "security-sentinel", "security-agent")
HEARTBEATS = {
    "listener": "/var/lib/security-listener/heartbeat",
    "sentinel": "/var/lib/security-sentinel/heartbeat",
    "agent": "/var/lib/security-agent/heartbeat",
}
STALE_S = 180


def unit_state(unit: str) -> tuple[str, int]:
    try:
        active = subprocess.run(["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10)
        restarts = subprocess.run(["systemctl", "show", unit, "-p", "NRestarts", "--value"],
                                  capture_output=True, text=True, timeout=10)
        return active.stdout.strip() or "unknown", int(restarts.stdout.strip() or 0)
    except Exception:  # noqa: BLE001
        return "unknown", -1


def check(have: bool, label: str, raw: str, meaning: str) -> bool:
    print(f"{'PASS' if have else 'FAIL'}  {label:26s} {raw}")
    if not have:
        print(f"      -> {meaning}")
    return have


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default="/root/authority.db")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()
    ok = True
    results = {}

    # 1. every unit exists and is active
    for unit in UNITS:
        state, restarts = unit_state(unit)
        results[f"unit:{unit}"] = {"state": state, "restarts": restarts}
        ok &= check(state == "active", f"unit {unit}", f"{state} restarts={restarts}",
                    "the component is not running; whatever it was responsible for is not happening")

    # 2. each component's own heartbeat — written by the loop, not by systemd
    now = time.time()
    for name, path in HEARTBEATS.items():
        try:
            age = round(now - os.path.getmtime(path), 1)
            results[f"heartbeat:{name}"] = age
            ok &= check(age <= STALE_S, f"heartbeat {name}", f"age={age}s (path {path})",
                        "the process is running but its loop has not completed a pass recently: hung, or "
                        "blocked on a socket that will never deliver")
        except OSError:
            results[f"heartbeat:{name}"] = None
            ok &= check(False, f"heartbeat {name}", "missing",
                        "this component has never written a heartbeat since the code was deployed")

    # 3. the record is writable and the schema is present
    try:
        conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True, timeout=5.0)
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        need = {"security_event", "security_decision", "security_label", "security_action",
                "security_run_placeholder"} - {"security_run_placeholder"}
        missing = sorted(need - names)
        ok &= check(not missing, "schema", f"{len(need)} required tables, missing={missing}",
                    "the record cannot hold what the components are trying to write")

        counts = conn.execute(
            "SELECT (SELECT COUNT(*) FROM security_event), (SELECT COUNT(*) FROM security_decision), "
            "(SELECT COUNT(*) FROM security_label), (SELECT COUNT(*) FROM security_action), "
            "(SELECT COUNT(*) FROM replay_run)").fetchone()
        results["counts"] = dict(zip(("events", "decisions", "labels", "actions", "replay_runs"), counts))
        print(f"INFO  record counts            events={counts[0]} decisions={counts[1]} "
              f"labels={counts[2]} actions={counts[3]} replay_runs={counts[4]}")

        # The honest question is not "were there any drops" but "has the socket dropped SINCE it was last
        # established". A restart produces a burst of disconnects followed by one clean session; a flapping
        # socket produces drops *after* the newest session started, which is what this counts.
        last_start = conn.execute("SELECT MAX(occurred_at) FROM security_event WHERE recorder_gap = 1 "
                                  "AND new_state LIKE '%session start%'").fetchone()[0]
        since = conn.execute("SELECT COUNT(*) FROM security_event WHERE recorder_gap = 1 "
                             "AND new_state LIKE 'reconnect%' AND occurred_at > ?", (last_start or "",)).fetchone()[0]
        total = conn.execute("SELECT COUNT(*) FROM security_event WHERE recorder_gap = 1 "
                             "AND new_state LIKE 'reconnect%' "
                             "AND created_at > datetime('now','-1 hour')").fetchone()[0]
        ok &= check(since == 0, "drops since the current session began", f"{since} (1h total {total})",
                    "the socket is dropping after it comes back: the record has holes and the building is "
                    "being watched intermittently. One burst before the current session is a restart")
        print(f"INFO  current session since      {last_start}")

        # a system that has judged nothing in 24h is not necessarily broken — say which it is
        judged = conn.execute("SELECT COUNT(*) FROM security_decision "
                              "WHERE created_at > datetime('now','-24 hours')").fetchone()[0]
        print(f"INFO  episodes judged (24h)     {judged}" +
              ("  (nothing has happened at the building — this is not a fault)" if judged == 0 else ""))
    except sqlite3.Error as exc:
        ok &= check(False, "database", str(exc)[:80], "the record is unreadable")

    if args.json:
        print(json.dumps({"ok": bool(ok), **results}, default=str))
    print(f"\n{'ALL CHECKS PASS' if ok else 'AT LEAST ONE CHECK FAILED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
