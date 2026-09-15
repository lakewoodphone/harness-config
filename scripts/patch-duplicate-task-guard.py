#!/usr/bin/env python3
"""Make the duplicate-task guard able to see the tasks it exists to catch.

MEASURED on secratary 2026-09-15. Task #25106 (a $167.96 PayPal dispute) collected FIVE
tasks about the same order in three hours: 1777, 25106, 25117, 25158, 25174, and 25179 --
three of them near-identical titles. `create_task` already dedupes (an exact `dedupe_key`
path and a fuzzy `find_similar_open_tasks` at 80% word overlap), so the question was not
"why is there no guard" but "why could the guard not see it". Two answers, both narrow:

  1. THE LIVE SET IS TOO SMALL. `find_similar_open_tasks` matches
     `status IN ('open','in_progress')`. At 00:45, when duplicate #25158 was created,
     #25106 was `blocked` -- put there by the retry ceiling added an hour earlier. So
     blocking a task licensed the creation of duplicates of it. The table also holds
     'in-progress' (3 rows), 'todo' (1), 'waiting on customer' (3), 'awaiting_part' (1)
     and 'paused' (1): all of them tasks with work still pending, none of them visible.
     This is the same shape as journal L1477 -- a row whose state is outside the set every
     query filters on is invisible to the guard -- and this time I caused it myself.

  2. THE SCAN IS AGENT-SCOPED. `create_task` passes `agent_id=agent_id`, so the fuzzy check
     only considers tasks created by the caller. Duplicate #25174 was filed by dept_finance
     against a task created by orchestrator, so it could never match. A duplicate is a
     duplicate whoever filed it; chat_action_tasks.py already does a global scan
     (`global_similar`) for exactly this reason, so the DB writer was the inconsistent one.

Added 2026-09-15: the third duplicate, #25174 at 01:09, was created while #25106 was
falsely `done` from a rollup -- the false-completion bug fixed the same night (commit
e88dccff). So two of the three duplicates trace to guards of mine that could not see what
was in front of them.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_CONST = 'TASK_ACTIVE_STATUSES = ("open", "in_progress", "pending", "blocked")'
NEW_CONST = '''TASK_ACTIVE_STATUSES = ("open", "in_progress", "pending", "blocked")

# The statuses in which a task still has work pending, which is a DIFFERENT question from
# "is this task consuming ceiling capacity" (that is TASK_ACTIVE_STATUSES). Duplicate
# detection asks the first question, and answering it with the second set is how three
# duplicates of task #25106 were created: a `blocked` task was invisible, so blocking it
# licensed copies of it. The extra values below are not invented -- each one appears in the
# live table (measured 2026-09-15: 'waiting on customer' 3, 'in-progress' 3,
# 'awaiting_part' 1, 'paused' 1, 'todo' 1).
TASK_PENDING_WORK_STATUSES = TASK_ACTIVE_STATUSES + (
    "in-progress",
    "todo",
    "waiting_on_customer",
    "waiting on customer",
    "awaiting_part",
    "paused",
)'''

OLD_QUERY = '''    query = """SELECT id, title, priority, status, assigned_to, agent_id
               FROM tasks
               WHERE status IN ('open', 'in_progress')"""'''

NEW_QUERY = '''    query = (
        "SELECT id, title, priority, status, assigned_to, agent_id "
        "FROM tasks WHERE status IN (%s)"
        % ", ".join("?" * len(TASK_PENDING_WORK_STATUSES))
    )
    params.extend(TASK_PENDING_WORK_STATUSES)'''

OLD_CALL = '''            dupes = find_similar_open_tasks(
                db_url,
                title,
                agent_id=agent_id,
                similarity_threshold=dedup_threshold,
            )'''

NEW_CALL = '''            # agent_id=None: a duplicate is a duplicate whoever filed it. Scoping this to
            # the caller let dept_finance create #25174 against orchestrator's #25106 at
            # 80% word overlap without either side noticing.
            dupes = find_similar_open_tasks(
                db_url,
                title,
                agent_id=None,
                similarity_threshold=dedup_threshold,
            )'''

TEST = '''"""The duplicate-task guard must be able to see the dupes it exists to stop.

Measured 2026-09-15: task #25106, a $167.96 dispute, collected five tasks about the same
order in three hours. Two of the duplicates were invisible to the guard for two different
reasons, both narrow:

  * #25158 was created while #25106 was `blocked`, a state the guard did not scan, so
    blocking a task licensed copies of it;
  * #25174 was filed by dept_finance against orchestrator's task, and the guard was scoped
    to the caller's own agent_id.
"""

import sqlite3

from app.database import TASK_ACTIVE_STATUSES, TASK_PENDING_WORK_STATUSES, find_similar_open_tasks

TITLE = ("File PayPal item-not-received dispute for Global Direct Parts order 161898 "
         "($167.96, paid 2026-04-19, never shipped) - hard deadline 2026-10-16")


def _scratch(tmp_path, rows):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript(
        "create table tasks (id integer primary key, title text, priority text, "
        "status text, assigned_to text, agent_id text, created_at text);"
    )
    for i, (status, agent) in enumerate(rows, start=1):
        con.execute(
            "insert into tasks (id, title, priority, status, assigned_to, agent_id, created_at) "
            "values (?,?,?,?,?,?,?)",
            (i, TITLE, "medium", status, None, agent, f"2026-09-15T0{i}:00:00+00:00"),
        )
    con.commit()
    con.close()
    return str(path)


def _match(url, agent=None):
    return [d["id"] for d in find_similar_open_tasks(url, TITLE, agent_id=agent,
                                                    similarity_threshold=80)]


def test_a_blocked_task_is_visible(tmp_path):
    """Blocking a task must not license duplicates of it."""
    url = _scratch(tmp_path, [("blocked", "orchestrator")])
    assert _match(url, "orchestrator") == [1]


def test_the_other_pending_work_states_are_visible(tmp_path):
    for status in ("waiting on customer", "awaiting_part", "paused", "todo", "in-progress"):
        url = _scratch(tmp_path, [(status, "orchestrator")])
        assert _match(url, "orchestrator") == [1], status


def test_a_finished_task_is_not_a_duplicate(tmp_path):
    for status in ("done", "completed", "closed", "cancelled"):
        url = _scratch(tmp_path, [(status, "orchestrator")])
        assert _match(url, "orchestrator") == [], status


def test_a_global_scan_catches_another_agents_duplicate(tmp_path):
    """#25174 was filed by dept_finance against orchestrator's task."""
    url = _scratch(tmp_path, [("in_progress", "orchestrator")])
    assert _match(url, "dept_finance") == []        # scoped: the old blind spot
    assert _match(url, None) == [1]                 # global: what create_task now uses


def test_the_pending_work_set_contains_the_active_set():
    """One must not silently drift from the other."""
    assert set(TASK_ACTIVE_STATUSES) <= set(TASK_PENDING_WORK_STATUSES)


def test_create_task_scans_globally():
    """Wiring: asserted separately from the helper, because a fix attached to the wrong
    call site is the mistake this session made twice."""
    import ast
    import pathlib

    src = pathlib.Path(__file__).resolve().parents[1] / "app" / "database.py"
    tree = ast.parse(src.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "create_task":
            for call in ast.walk(node):
                if (isinstance(call, ast.Call)
                        and isinstance(call.func, ast.Name)
                        and call.func.id == "find_similar_open_tasks"):
                    kw = {k.arg: k.value for k in call.keywords}
                    assert "agent_id" in kw, "the call must state its scope explicitly"
                    assert isinstance(kw["agent_id"], ast.Constant) and kw["agent_id"].value is None
                    return
            raise AssertionError("create_task does not call find_similar_open_tasks")
    raise AssertionError("create_task not found")
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")

    assert src.count(OLD_CONST) == 1, f"constant: {src.count(OLD_CONST)}"
    assert "TASK_PENDING_WORK_STATUSES" not in src
    assert src.count(OLD_QUERY) == 1, f"query: {src.count(OLD_QUERY)}"
    assert src.count(OLD_CALL) == 1, f"call: {src.count(OLD_CALL)}"

    backup = BACKUPS / f"database.py.{STAMP}.bak11"
    if not backup.exists():
        shutil.copy("app/database.py", backup)

    src = src.replace(OLD_CONST, NEW_CONST, 1)
    src = src.replace(OLD_QUERY, NEW_QUERY)
    src = src.replace(OLD_CALL, NEW_CALL)
    db.write_text(src, encoding="utf-8")
    print("patched app/database.py")

    pathlib.Path("tests/test_duplicate_task_guard.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_duplicate_task_guard.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
