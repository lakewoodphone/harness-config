#!/usr/bin/env python3
"""Stop re-running a task that keeps failing, instead of paying for the same failure again.

MEASURED, secratary 2026-09-15 00:28: task #25106 has been attempted five times in 90
minutes (75405, 75406, 75407, 75415, 75416), every attempt dying at the step budget, and
all 28 work-session failures in the previous three hours were that same budget. Task
#25118 was attempted three times. Re-running bought nothing: 75415 was given four
extensions up to the absolute cap and still failed.

Nothing in the loop notices that the work has already been attempted and failed. A job
exists, so a session is created, so the same five-to-fifteen LLM steps are spent again.
Persistence is not the same as repetition.

WHAT THIS DOES: before creating a work session, count this task's RECENT failed sessions.
At the threshold the task is marked blocked and the job is closed with a stated reason, so
no further LLM budget is spent on it. Recency matters -- a task that failed three times
last week and has new work today must not be blocked, which is why the count is bounded to
the last 24 hours rather than all time.

The job is COMPLETED (with reason not_retried) rather than failed, matching the existing
completed-task guard, so the queue does not re-enqueue it and loop. The truth is carried in
the task's own status.
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

FUNC = '''def count_recent_failed_work_sessions(
    db_url: str,
    task_id: int | None,
    *,
    within_hours: int = 24,
) -> int:
    """How many work sessions have already failed on this task recently.

    Nothing else notices that the same work has been attempted and failed: a job
    exists, so a session is created, so the same LLM budget is spent again. Measured
    2026-09-15: task #25106 was attempted five times in ninety minutes and every attempt
    died at the step budget.

    Bounded to recent failures on purpose. A task that failed three times last week and
    has new work today is not the same situation as one failing three times this hour,
    and blocking the former would be a silent loss of work.
    """
    if not task_id:
        return 0
    from datetime import datetime, timedelta, timezone

    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=max(1, int(within_hours)))
    ).isoformat()
    conn = _get_conn(db_url)
    row = conn.execute(
        "SELECT count(*) FROM work_sessions "
        "WHERE task_id = ? AND status = 'failed' AND started_at >= ?",
        (int(task_id), cutoff),
    ).fetchone()
    return int(row[0] if row else 0)


def retire_abandoned_running_jobs('''

OLD_IMPORT = "            retire_abandoned_running_jobs,"
NEW_IMPORT = (
    "            retire_abandoned_running_jobs,\n"
    "            count_recent_failed_work_sessions,"
)

OLD_SITE = '''                except Exception:
                    pass

            target_agent_id = None'''

NEW_SITE = '''                except Exception:
                    pass

            # ── Repeated-failure guard: stop paying for the same failure ──
            # Measured 2026-09-15: task #25106 was attempted 5 times in 90 minutes and
            # every attempt died at the step budget; #25118 three times. The session just
            # below this point costs 5 to 11 LLM steps, and nothing had noticed that the
            # work had already been attempted and failed.
            if task_id is not None:
                try:
                    _prior_failures = count_recent_failed_work_sessions(
                        db_url=self._db_url,
                        task_id=task_id,
                    )
                    if _prior_failures >= self._WORK_MAX_FAILED_ATTEMPTS:
                        update_task(
                            db_url=self._db_url,
                            task_id=task_id,
                            status="blocked",
                        )
                        complete_job(
                            db_url=self._db_url,
                            job_id=job["id"],
                            result={
                                "status": "not_retried",
                                "reason": (
                                    f"task #{task_id} failed {_prior_failures} work "
                                    "session(s) in the last 24h; marked blocked instead "
                                    "of re-running it"
                                ),
                            },
                        )
                        proactive_actions.append(
                            f"Stopped retrying task #{task_id}: {_prior_failures} failed "
                            "work session(s) in 24h; marked blocked"
                        )
                        return None
                except Exception as _exc:
                    logger.warning(
                        "repeated-failure guard for task %s: %s", task_id, _exc
                    )

            target_agent_id = None'''

OLD_CONST = "    _WORK_MAX_EXTENSIONS = 2"
NEW_CONST = """    _WORK_MAX_EXTENSIONS = 2
    # How many recent failed sessions on one task before it stops being re-run. Two is
    # not enough to distinguish a transient fault from a task that cannot be done; five
    # is paid for five times over.
    _WORK_MAX_FAILED_ATTEMPTS = 3"""

TEST = '''"""A task that keeps failing must stop being re-run from scratch.

Measured on secratary 2026-09-15: task #25106 was attempted five times in ninety minutes,
every attempt dying at the step budget, and all 28 failures in three hours were that same
budget. Task #25118 was attempted three times. The loop had no notion that the work had
already been attempted and failed.
"""

import ast
import datetime
import pathlib
import sqlite3

from app.database import count_recent_failed_work_sessions


def _scratch(tmp_path):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript("""
        create table work_sessions (
            id integer primary key, task_id integer, status text, started_at text
        );
    """)
    con.commit()
    con.close()
    return str(path)


def _add(url, task_id, status, started_at):
    con = sqlite3.connect(url)
    con.execute(
        "insert into work_sessions (task_id, status, started_at) values (?,?,?)",
        (task_id, status, started_at),
    )
    con.commit()
    con.close()


def _ago(hours):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(hours=hours)).isoformat()


def test_counts_recent_failures_for_the_task(tmp_path):
    url = _scratch(tmp_path)
    _add(url, 25106, "failed", _ago(1))
    _add(url, 25106, "failed", _ago(2))
    _add(url, 25106, "completed", _ago(1))   # not a failure
    _add(url, 99999, "failed", _ago(1))      # a different task
    assert count_recent_failed_work_sessions(url, 25106) == 2


def test_old_failures_do_not_count(tmp_path):
    """A task that failed last week and has new work today must not be blocked."""
    url = _scratch(tmp_path)
    _add(url, 25106, "failed", _ago(72))
    _add(url, 25106, "failed", _ago(48))
    assert count_recent_failed_work_sessions(url, 25106, within_hours=24) == 0


def test_no_task_id_is_zero(tmp_path):
    url = _scratch(tmp_path)
    assert count_recent_failed_work_sessions(url, None) == 0
    assert count_recent_failed_work_sessions(url, 0) == 0


def test_the_guard_is_wired_into_the_claim_path():
    """The wiring, asserted separately from the helper's logic.

    Twice tonight a change was attached to the wrong branch and the unit tests for its
    helper passed while the feature did nothing.
    """
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "autopilot.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_work_queue":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Name)
                and n.func.id == "count_recent_failed_work_sessions"
            ]
            assert len(calls) == 1, f"expected 1 call, found {len(calls)}"
            return
    raise AssertionError("_process_work_queue not found")


def test_the_threshold_leaves_room_for_a_transient_fault():
    from app.autopilot import AutopilotController as AC

    assert 2 <= AC._WORK_MAX_FAILED_ATTEMPTS <= 5
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")
    ap = pathlib.Path("app/autopilot.py")
    asrc = ap.read_text(encoding="utf-8")

    assert src.count("def retire_abandoned_running_jobs(") == 1
    assert "count_recent_failed_work_sessions" not in src
    assert asrc.count(OLD_IMPORT) == 1, f"import: {asrc.count(OLD_IMPORT)}"
    assert asrc.count(OLD_SITE) == 1, f"site: {asrc.count(OLD_SITE)}"
    assert asrc.count(OLD_CONST) == 1, f"const: {asrc.count(OLD_CONST)}"

    for rel in ("app/database.py", "app/autopilot.py"):
        backup = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak"
        if not backup.exists():
            shutil.copy(rel, backup)

    src = src.replace("def retire_abandoned_running_jobs(", FUNC, 1)
    db.write_text(src, encoding="utf-8")

    asrc = asrc.replace(OLD_CONST, NEW_CONST, 1)
    asrc = asrc.replace(OLD_IMPORT, NEW_IMPORT)
    asrc = asrc.replace(OLD_SITE, NEW_SITE)
    ap.write_text(asrc, encoding="utf-8")
    print("patched app/database.py and app/autopilot.py")

    tree = ast.parse(asrc)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_work_queue":
            n = sum(
                1 for x in ast.walk(node)
                if isinstance(x, ast.Call) and isinstance(x.func, ast.Name)
                and x.func.id == "count_recent_failed_work_sessions"
            )
            assert n == 1, f"wiring check found {n} call(s)"
            print("confirmed: the guard is wired into the claim path")
            break

    pathlib.Path("tests/test_retry_ceiling.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_retry_ceiling.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
