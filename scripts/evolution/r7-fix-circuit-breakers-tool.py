#!/usr/bin/env python3
"""r7-fix-circuit-breakers-tool.py — make `ps_circuit_breakers` answer honestly instead of erroring.

THE DEFECT, hit by the manager 2026-10-15 while investigating TOOL_LOOP_DEADLOCK:

    ps_circuit_breakers  ->  {"error": "no such column: action_name"}

The tool body at `/opt/company/scripts/ps_mcp_server.py:850` runs

    SELECT action_name, state, failure_count, last_failure, cooldown_until
    FROM circuit_breaker_events ORDER BY last_failure DESC LIMIT 30

and **not one of those five columns exists**. Measured on `/root/authority.db`:

    circuit_breaker_events(id, agent_id, event_type, reason, spend_at_event, created_at)   20 rows
    circuit_breaker_state(agent_id, state, cooldown_until, tripped_at, reason,
                          failure_count, cooldown_sec, updated_at)                          0 rows

WHY THE QUERY CANNOT SIMPLY BE CORRECTED INTO THE SAME ANSWER: the breaker the tool's docstring
promises -- "which actions are currently broken/throttled" -- is **in process memory, not in the
database**. `app/chat_action_resilience.py:16` holds `_circuit_breaker: dict[str, dict[str, Any]] =
defaultdict(...)` with `_CB_THRESHOLD = 10` and `_CB_COOLDOWN = 120.0`. Nothing writes per-action
breaker state to SQLite; the two tables above are agent-level. So a rewritten SELECT against them
would answer a DIFFERENT question and say so in the tool's own docstring, which is how a defect like
this survives -- a tool that returns a confident, well-formed, irrelevant answer is worse than one
that errors.

WHAT THIS DOES: the tool reports what the database actually holds (agent-level state and recent
events), states plainly that the action-level breaker is per-process and unreadable from here, and
names the query that does answer it — counting `temporarily disabled` in `work_sessions.output_log`.
An honest partial answer plus the way to get the rest, in place of a traceback.

USAGE
    python3 r7-fix-circuit-breakers-tool.py            # measure only
    python3 r7-fix-circuit-breakers-tool.py --apply
"""
from __future__ import annotations

import argparse
import hashlib
import json
import py_compile
import shutil
import subprocess
import sys
from pathlib import Path

TARGET = Path("/opt/company/scripts/ps_mcp_server.py")
BACKUP_DIR = Path("/root/work/r6")

OLD = '''def ps_circuit_breakers() -> str:
    """List circuit breaker states — which actions are currently broken/throttled."""
    try:
        with _db() as conn:
            rows = conn.execute(
                "SELECT action_name, state, failure_count, last_failure, cooldown_until "
                "FROM circuit_breaker_events ORDER BY last_failure DESC LIMIT 30"
            ).fetchall()
            return json.dumps({"circuit_breakers": [dict(r) for r in rows]}, default=str)
    except Exception as exc:
        return json.dumps({"error": str(exc)})
'''

NEW = '''def ps_circuit_breakers() -> str:
    """Circuit breaker state — the AGENT-level breakers, and where the action-level ones live.

    CORRECTED 2026-10-15. This used to run

        SELECT action_name, state, failure_count, last_failure, cooldown_until
        FROM circuit_breaker_events

    and **none of those five columns exists in any table**, so every call returned
    `{"error": "no such column: action_name"}`. Measured schema:

        circuit_breaker_events(id, agent_id, event_type, reason, spend_at_event, created_at)
        circuit_breaker_state(agent_id, state, cooldown_until, tripped_at, reason,
                              failure_count, cooldown_sec, updated_at)

    The breaker this docstring used to promise — per ACTION — is not in the database at all:
    `app/chat_action_resilience.py` holds it in process memory (`_circuit_breaker`, threshold 10,
    cooldown 120 s). The two tables here are per AGENT. Rewriting the SELECT would therefore have
    answered a different question while still claiming to answer this one, which is worse than
    erroring — so this returns the agent-level truth, says what it cannot see, and hands over the
    query that does answer the action-level question.
    """
    out: dict[str, object] = {"schema_note": "agent-level breakers only; see action_level below"}
    try:
        with _db() as conn:
            try:
                st = conn.execute(
                    "SELECT agent_id, state, failure_count, cooldown_sec, cooldown_until, "
                    "tripped_at, reason, updated_at FROM circuit_breaker_state "
                    "ORDER BY updated_at DESC LIMIT 30"
                ).fetchall()
                out["agent_state"] = [dict(r) for r in st]
            except Exception as exc:  # a missing table is a finding, not a crash
                out["agent_state"] = []
                out["agent_state_error"] = str(exc)
            try:
                ev = conn.execute(
                    "SELECT id, agent_id, event_type, reason, spend_at_event, created_at "
                    "FROM circuit_breaker_events ORDER BY created_at DESC LIMIT 30"
                ).fetchall()
                out["recent_events"] = [dict(r) for r in ev]
            except Exception as exc:
                out["recent_events"] = []
                out["recent_events_error"] = str(exc)
    except Exception as exc:
        return json.dumps({"error": str(exc)})

    out["agent_state_rows"] = len(out.get("agent_state") or [])
    out["recent_event_rows"] = len(out.get("recent_events") or [])
    out["action_level"] = (
        "NOT IN THIS DATABASE. The per-action breaker lives in the memory of the company process "
        "that runs the action runtime (app/chat_action_resilience.py:16, _circuit_breaker, "
        "threshold 10 failures, cooldown 120 s) and cannot be read from SQLite. Count what it did "
        "to sessions instead: SELECT count(*) FROM work_sessions WHERE output_log LIKE "
        "'%temporarily disabled%' AND started_at >= <since>; and see which actions by extracting "
        "the [TOOL_LOOP_DEADLOCK: ...] markers from work_sessions.output_log."
    )
    return json.dumps(out, default=str)
'''


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    if not TARGET.is_file():
        print(f"! {TARGET} not found", file=sys.stderr)
        return 2
    text = TARGET.read_text(encoding="utf-8")
    print(f"target {TARGET}  sha256 {sha(TARGET)}")

    n = text.count(OLD)
    print(f"[1] the broken function occurs {n} time(s) (must be exactly 1)")
    if n != 1:
        print("! refusing: the anchor is not unique", file=sys.stderr)
        return 1

    new_text = text.replace(OLD, NEW, 1)
    # The old QUERY is the thing that must be gone -- grepping the whole file for `action_name` says
    # nothing, because other tools in this server legitimately use it. The first version of this
    # check did exactly that and printed "STILL PRESENT", which is noise, not a finding.
    old_query = ("SELECT action_name, state, failure_count, last_failure, cooldown_until "
                 "FROM circuit_breaker_events")
    print(f"[2] the broken QUERY is now present {new_text.count(old_query)} time(s) (must be 0)")
    if new_text.count(old_query) != 0:
        print("! refusing: the broken query survives", file=sys.stderr)
        return 1
    print(f"    NEW is in place: {new_text.count('agent-level breakers only')} marker(s)")

    if not args.apply:
        print("\nmeasure only -- nothing written. Re-run with --apply to install.")
        return 0

    stage = BACKUP_DIR / "r7-files6" / "ps_mcp_server.py"
    stage.parent.mkdir(parents=True, exist_ok=True)
    stage.write_text(new_text, encoding="utf-8")
    print(f"[3] staged -> {stage}  sha256 {sha(stage)}")
    print("    python syntax check:", end=" ")
    try:
        py_compile.compile(str(stage), doraise=True)
        print("OK")
    except py_compile.PyCompileError as exc:
        print(f"FAILED\n{exc}")
        return 1

    stamp = subprocess.run(["date", "-u", "+%Y%m%dT%H%M%SZ"], capture_output=True,
                           text=True).stdout.strip()
    backup = BACKUP_DIR / f"backups-cbtool-{stamp}" / "ps_mcp_server.py"
    backup.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, backup)
    print(f"[4] backup -> {backup}  sha256 {sha(backup)}")

    shutil.copy2(stage, TARGET)
    print(f"[5] installed  sha256 {sha(TARGET)}")
    if sha(TARGET) != sha(stage):
        print("! did not land byte-for-byte -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("    cmp: identical to the staged file")

    print("\n[6] PROOF -- call the function itself, in the interpreter the server actually runs under:")
    # NOT `sys.executable`. The first version imported the module in the invoking interpreter, which
    # for this script is /usr/bin/python3 and has no `mcp` package -- so the proof crashed on the
    # import while the install had already landed cleanly. Prove it where it runs.
    probe_py = "/opt/company/.venv/bin/python3"
    if not Path(probe_py).is_file():
        probe_py = sys.executable
    probe = subprocess.run(
        [probe_py, "-c",
         "import sys; sys.path.insert(0,'/opt/company/scripts');"
         "import ps_mcp_server as m; print(m.ps_circuit_breakers())"],
        capture_output=True, text=True)
    out = (probe.stdout or "").strip()
    if probe.returncode != 0:
        print(f"      probe FAILED rc={probe.returncode}: {(probe.stderr or '')[-300:]}")
        print(f"! restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print("      " + out[:420].replace("\n", " "))
    try:
        parsed = json.loads(out)
    except Exception as exc:
        print(f"! probe output is not JSON ({exc}) -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    ok = "error" not in parsed and "action_level" in parsed
    print(f"      no error, and it names where the action-level breaker lives: {ok}")
    if not ok:
        print("! the tool still fails -- restoring from backup", file=sys.stderr)
        shutil.copy2(backup, TARGET)
        return 1
    print(f"\n    rollback: cp -p {backup} {TARGET}")
    print("    NOTE: an MCP server already spawned holds the OLD module. The next spawn of")
    print("    ps_mcp_server.py picks this up; a session that has already started will not.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

