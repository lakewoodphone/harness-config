#!/usr/bin/env python3
"""Retire jobs stuck in 'running' that no cleanup path will ever reach.

MEASURED on secratary 2026-09-14: job_queue holds 9 rows in status 'running' whose
ages are 59,432 to 130,844 minutes -- 41 to 90 days. Their `picked_up_at` is NULL,
which is the first clue, and the second is that requeue_stale_running_jobs filters
`WHERE agent_id = ?`: the work loop calls it with its own agent id, so a job claimed by
dept_world_index, engineering_indexer, finance_floor_manager, model_ops_evaluator or
dept_home_life is never examined again by anyone. Those agents are all still present in
agent_metrics, so this is not retired staff -- the cleanup simply never looks at them.

Consequence: `select count(*) from job_queue where status='running'` is not a measure of
work in flight. It reads 10 when 1 is true. Judgements about whether the fleet is busy,
saturated, or stalled have been made from that number.

TWO CONDITIONS, NOT ONE. They must be waived because the oldest rows predate the
column, and because an agent-scoped sweep cannot see another agent's work:
  * drop the agent filter -- this is a queue-wide maintenance action
  * fall back to created_at when picked_up_at is NULL

DISPOSITION: a job stuck for more than a day is not late work, and requeueing it would
spend fresh LLM budget on a stale task; completed-task jobs are already handled by
complete_stale_task_jobs, which runs first. So anything still running past the bound is
FAILED with a stated reason, which removes it from every in-flight metric without
pretending it succeeded. The bound is generous (24h) because a slow agent may legitimately
work for hours.
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

FUNC = '''def retire_abandoned_running_jobs(
    db_url: str,
    *,
    older_than_hours: int = 24,
    note: str = "abandoned: stuck in running with no reachable cleanup",
) -> int:
    """Fail jobs that have been 'running' longer than any plausible work session.

    Two conditions are deliberately waived, because both hid real rows:
      * the agent filter -- requeue_stale_running_jobs is scoped to one agent, so a
        job claimed by any other agent is never examined again. Nine such rows sat
        running for 41 to 90 days.
      * `picked_up_at IS NOT NULL` -- the oldest rows predate the column, so
        requiring it made them permanently invisible.

    Completed-task jobs are the caller's business (complete_stale_task_jobs runs
    first); what is left here is work nobody will ever pick up, so it is failed with
    a reason rather than requeued into fresh LLM spend.
    """
    from datetime import datetime, timedelta, timezone

    conn = _get_conn(db_url)
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(hours=max(1, int(older_than_hours)))).isoformat()
    with _db_lock:
        cur = conn.execute(
            "UPDATE job_queue "
            "SET status = 'failed', completed_at = ?, error_message = ? "
            "WHERE status = 'running' "
            "AND coalesce(picked_up_at, created_at) < ?",
            (now.isoformat(), note, cutoff),
        )
        conn.commit()
        return int(cur.rowcount or 0)


def requeue_stale_running_jobs('''

OLD_IMPORT = "            requeue_stale_running_jobs,"
NEW_IMPORT = "            requeue_stale_running_jobs,\n            retire_abandoned_running_jobs,"

OLD_CALL = '''            completed_stale = complete_stale_task_jobs(
                db_url=self._db_url,
                limit=1000,
            )
            if completed_stale:
                proactive_actions.append(
                    f"Completed {completed_stale} stale task job(s)"
                )'''

NEW_CALL = '''            completed_stale = complete_stale_task_jobs(
                db_url=self._db_url,
                limit=1000,
            )
            if completed_stale:
                proactive_actions.append(
                    f"Completed {completed_stale} stale task job(s)"
                )

            # Queue-wide, not agent-scoped, and tolerant of a NULL picked_up_at:
            # 9 jobs had been 'running' for 41-90 days because the only requeue path
            # filters on one agent id and requires that column.
            retired = retire_abandoned_running_jobs(db_url=self._db_url)
            if retired:
                proactive_actions.append(f"Retired {retired} abandoned running job(s)")'''

TEST = '''"""A job stuck in 'running' must eventually leave that state.

Nine rows in job_queue sat in 'running' for 41 to 90 days (secratary, 2026-09-14).
requeue_stale_running_jobs could not see them: it filters on a single agent_id, and
it requires picked_up_at IS NOT NULL, which the oldest rows predate. So
`count(*) where status='running'` read 10 when 1 was true.
"""

import sqlite3

from app.database import retire_abandoned_running_jobs


def _scratch(tmp_path):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript("""
        create table job_queue (
            id integer primary key, agent_id text, job_type text, title text,
            payload_json text, status text, priority integer, retry_count integer,
            max_retries integer, error_message text, result_json text,
            created_at text, picked_up_at text, completed_at text
        );
    """)
    con.commit()
    con.close()
    return str(path)


def _insert(url, id_, agent, created, picked):
    con = sqlite3.connect(url)
    con.execute(
        "insert into job_queue (id, agent_id, job_type, status, retry_count, "
        "created_at, picked_up_at) values (?,?,'task_execution','running',0,?,?)",
        (id_, agent, created, picked),
    )
    con.commit()
    con.close()


def _statuses(url):
    con = sqlite3.connect(url)
    rows = dict(con.execute("select id, status from job_queue"))
    con.close()
    return rows


def test_an_ancient_job_from_another_agent_is_retired(tmp_path):
    url = _scratch(tmp_path)
    _insert(url, 1, "dept_world_index", "2026-06-01T00:00:00+00:00", None)   # NULL pickup
    _insert(url, 2, "finance_floor_manager", "2026-07-01T00:00:00+00:00", "2026-07-01T00:00:00+00:00")
    retired = retire_abandoned_running_jobs(url, older_than_hours=24)
    assert retired == 2
    assert _statuses(url) == {1: "failed", 2: "failed"}


def test_a_legitimately_running_job_is_untouched(tmp_path):
    url = _scratch(tmp_path)
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    _insert(url, 3, "dept_engineering", now, now)
    assert retire_abandoned_running_jobs(url, older_than_hours=24) == 0
    assert _statuses(url) == {3: "running"}


def test_non_running_jobs_are_never_touched(tmp_path):
    url = _scratch(tmp_path)
    con = sqlite3.connect(url)
    con.execute(
        "insert into job_queue (id, agent_id, job_type, status, retry_count, created_at) "
        "values (4,'x','task_execution','pending',0,'2026-01-01T00:00:00+00:00')"
    )
    con.execute(
        "insert into job_queue (id, agent_id, job_type, status, retry_count, created_at) "
        "values (5,'x','task_execution','completed',0,'2026-01-01T00:00:00+00:00')"
    )
    con.commit()
    con.close()
    assert retire_abandoned_running_jobs(url, older_than_hours=24) == 0
    assert _statuses(url) == {4: "pending", 5: "completed"}
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")
    ap = pathlib.Path("app/autopilot.py")
    asrc = ap.read_text(encoding="utf-8")

    assert src.count("def requeue_stale_running_jobs(") == 1
    assert "retire_abandoned_running_jobs" not in src
    assert asrc.count(OLD_IMPORT) == 1, f"import: {asrc.count(OLD_IMPORT)}"
    assert asrc.count(OLD_CALL) == 1, f"call site: {asrc.count(OLD_CALL)}"

    for rel in ("app/database.py", "app/autopilot.py"):
        backup = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak"
        if not backup.exists():
            shutil.copy(rel, backup)

    src = src.replace("def requeue_stale_running_jobs(", FUNC, 1)
    db.write_text(src, encoding="utf-8")
    asrc = asrc.replace(OLD_IMPORT, NEW_IMPORT).replace(OLD_CALL, NEW_CALL)
    ap.write_text(asrc, encoding="utf-8")
    print("patched app/database.py and app/autopilot.py")

    pathlib.Path("tests/test_abandoned_jobs.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_abandoned_jobs.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
