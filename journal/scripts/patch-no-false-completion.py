#!/usr/bin/env python3
"""Refuse to mark a task done when the only evidence is rollup over failure.

MEASURED on secratary 2026-09-15, and it is the dangerous kind of wrong -- silent and
permanent:

  task #25106  five failed work sessions, ZERO successful ones  ->  status 'done'
               a real $167.96 PayPal item-not-received dispute with a hard deadline of
               2026-10-16. Its goal plan had actually gone to 'failed'.
  task #25118  three failed work sessions, zero successful      ->  status 'done'

Both were closed by a rollup: #25118's goal_plans row is status 'completed' with
updated_at matching the task's completed_at to the microsecond. Nothing retries a task
that is done and no error is raised anywhere, so the work is buried. An entire recent
wave (tasks 25103-25120) is 'done', including the ones whose sessions all failed.

WHY THE WRITER: the closures come from at least four paths -- lifecycle_sweep's
completed-progress and stale-task phases, the goal rollup, and workflow_engine's parent
closure -- so a guard in any one of them leaves the others open. Same reasoning as
_WORK_SESSION_STATUSES: declare the rule where the value is written.

WHY THE CONDITION IS NARROW: closing a task is usually legitimate. Refuse only when all
three hold -- no work session is ACTIVE for this task right now, at least one recent
session FAILED, and NONE completed. An active session means a session is finishing and
closing its own task (the [WORK_DONE] path calls update_task(status="done") while its own
session is still active); a completed session means real work succeeded. Anything else is
a rollup over failure.
"""

from __future__ import annotations

import ast
import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

HELPER = '''def _task_close_would_be_a_lie(
    conn: Any,
    task_id: int,
    *,
    within_hours: int = 24,
) -> str:
    """Why closing this task as done would record work that did not happen, or "".

    Measured 2026-09-15: tasks #25106 (five failed work sessions, none successful) and
    #25118 (three failed, none successful) were both set to 'done' by rollups. #25106 is
    a real $167.96 PayPal dispute with a hard deadline, and its goal plan had gone to
    'failed' -- the task was closed anyway. Nothing retries a task that is done and
    nothing raises, so a false 'done' buries the work permanently.

    Returns "" (allow) unless all three hold: no session ACTIVE, at least one recent
    failure, and no recent completion. A failure of this check itself returns "" -- a
    close must never be blocked because the check could not run.
    """
    from datetime import datetime, timedelta, timezone

    try:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=max(1, int(within_hours)))
        ).isoformat()
        row = conn.execute(
            """
            SELECT
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'active') AS active,
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'failed' AND started_at >= ?) AS failed,
              (SELECT count(*) FROM work_sessions
                WHERE task_id = ? AND status = 'completed' AND started_at >= ?)
                AS completed
            """,
            (int(task_id), int(task_id), cutoff, int(task_id), cutoff),
        ).fetchone()
    except Exception:  # noqa: BLE001 - an unanswerable check must not block a close
        return ""
    if not row:
        return ""
    active, failed, completed = (int(row[0] or 0), int(row[1] or 0), int(row[2] or 0))
    if active or completed or not failed:
        return ""
    return (
        f"{failed} recent work session(s) failed and none succeeded, and no session is "
        "active now"
    )


def update_task('''

OLD_GUARD = """    conn = _get_conn(db_url)
    now = _now_iso()
    completing = status in TASK_COMPLETED_STATUSES
    assigned_to = canonicalize_assignment_agent(assigned_to)"""

NEW_GUARD = """    conn = _get_conn(db_url)
    now = _now_iso()
    completing = status in TASK_COMPLETED_STATUSES
    if completing:
        # Refuse a completion that rests on nothing but failure. See
        # _task_close_would_be_a_lie: four different rollup paths close tasks, so the rule
        # lives at the writer rather than in each of them.
        _lie = _task_close_would_be_a_lie(conn, int(task_id))
        if _lie:
            logging.getLogger(__name__).warning(
                "update_task(%s): refusing to mark %r -- %s",
                task_id,
                status,
                _lie,
            )
            status = None
            completing = False
    assigned_to = canonicalize_assignment_agent(assigned_to)"""

TEST = '''"""A task must not be marked done when the only evidence is rollup over failure.

Measured on secratary 2026-09-15: task #25106 (five failed work sessions, none successful)
was set to 'done' -- a real $167.96 PayPal dispute with a hard deadline, whose goal plan had
actually failed. Task #25118 (three failed, none successful) likewise. Nothing retries a
done task and nothing raises, so the work is buried.
"""

import ast
import datetime
import pathlib
import sqlite3

from app.database import _task_close_would_be_a_lie

SCHEMA = """
create table work_sessions (
    id integer primary key, task_id integer, status text, started_at text
);
"""


def _scratch(tmp_path, rows=()):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    for task_id, status, hours_ago in rows:
        ts = (datetime.datetime.now(datetime.timezone.utc)
              - datetime.timedelta(hours=hours_ago)).isoformat()
        con.execute(
            "insert into work_sessions (task_id, status, started_at) values (?,?,?)",
            (task_id, status, ts),
        )
    con.commit()
    return con


def test_refuses_when_only_failures_exist(tmp_path):
    con = _scratch(tmp_path, [(25106, "failed", 1), (25106, "failed", 2)])
    assert _task_close_would_be_a_lie(con, 25106) != ""


def test_allows_when_a_session_completed(tmp_path):
    """Real work succeeded, so the close is earned."""
    con = _scratch(tmp_path, [(25129, "failed", 2), (25129, "completed", 1)])
    assert _task_close_would_be_a_lie(con, 25129) == ""


def test_allows_while_a_session_is_active(tmp_path):
    """The [WORK_DONE] path closes its own task while its session is still active."""
    con = _scratch(tmp_path, [(25136, "failed", 1), (25136, "active", 0)])
    assert _task_close_would_be_a_lie(con, 25136) == ""


def test_allows_when_nothing_ever_failed(tmp_path):
    con = _scratch(tmp_path, [(1, "paused", 1)])
    assert _task_close_would_be_a_lie(con, 1) == ""


def test_old_failures_do_not_block_a_close(tmp_path):
    con = _scratch(tmp_path, [(1, "failed", 72)])
    assert _task_close_would_be_a_lie(con, 1) == ""


def test_an_unanswerable_check_does_not_block(tmp_path):
    con = sqlite3.connect(":memory:")  # no work_sessions table at all
    assert _task_close_would_be_a_lie(con, 1) == ""


def test_the_guard_is_wired_into_update_task():
    """Wiring asserted separately from the helper -- twice tonight a change was attached
    to the wrong branch and the helper's own tests passed while nothing ran."""
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "database.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "update_task":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "_task_close_would_be_a_lie"
            ]
            assert len(calls) == 1, f"expected 1 call, found {len(calls)}"
            return
    raise AssertionError("update_task not found")
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")

    assert src.count("def update_task(") == 1
    assert "_task_close_would_be_a_lie" not in src
    assert src.count(OLD_GUARD) == 1, f"guard site: {src.count(OLD_GUARD)}"
    assert "import logging" in src

    backup = BACKUPS / f"database.py.{STAMP}.bak10"
    if not backup.exists():
        shutil.copy("app/database.py", backup)

    src = src.replace("def update_task(", HELPER, 1)
    src = src.replace(OLD_GUARD, NEW_GUARD)
    db.write_text(src, encoding="utf-8")
    print("patched app/database.py")

    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "update_task":
            n = sum(
                1 for x in ast.walk(node)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                and x.func.id == "_task_close_would_be_a_lie"
            )
            assert n == 1, f"wiring: {n} call(s)"
            print("confirmed: the guard is wired into update_task")
            break

    pathlib.Path("tests/test_no_false_task_completion.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_no_false_task_completion.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
