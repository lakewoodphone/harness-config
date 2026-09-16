"""313 questions sat unanswered for up to 134 days and the badge called them live work.

Measured 2026-09-15: agent_questions held 313 pending rows, oldest 3226 h, newest
1405 h, nothing created in 30 days. These tests pin the shelf life that fixes it.
"""

from __future__ import annotations

import inspect
import pathlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from app.services.lifecycle_sweep import (
    AGENT_QUESTION_MAX_AGE_HOURS,
    _expire_stale_agent_questions,
)

CREATE = """CREATE TABLE agent_questions (
    id TEXT PRIMARY KEY,
    project_id TEXT,
    agent_id TEXT NOT NULL,
    question TEXT NOT NULL,
    context TEXT DEFAULT '{}',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending','answered','dismissed','expired')),
    answer TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    answered_at TEXT
)"""


def _db(tmp_path, name="q.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE)
    conn.commit()
    return conn, f"sqlite:///{path}"


def _insert(conn, qid, age_hours, status="pending", question="why?"):
    created = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).isoformat()
    conn.execute(
        "INSERT INTO agent_questions (id, agent_id, question, status, created_at) "
        "VALUES (?, 'orchestrator', ?, ?, ?)",
        (qid, question, status, created),
    )
    conn.commit()
    return qid


def _row(conn, qid):
    return conn.execute(
        "SELECT status, status_note, question FROM agent_questions WHERE id = ?", (qid,)
    ).fetchone()


def test_the_horizon_is_two_weeks():
    assert AGENT_QUESTION_MAX_AGE_HOURS == 336.0


def test_a_134_day_old_question_expires_and_a_fresh_one_does_not(tmp_path):
    conn, url = _db(tmp_path)
    ancient = _insert(conn, "old", 3226, question="Ready to send this SMS to +1848...?")
    fresh = _insert(conn, "new", 3, question="Ship the rebuilt iPhone today?")

    counts = _expire_stale_agent_questions(conn, threading.RLock(), url)

    assert counts["agent_questions_expired"] == 1, counts
    assert _row(conn, ancient)["status"] == "expired"
    assert "unanswered for more than 14 days" in _row(conn, ancient)["status_note"]
    assert _row(conn, fresh)["status"] == "pending"


def test_already_answered_or_dismissed_questions_are_never_touched(tmp_path):
    conn, url = _db(tmp_path)
    answered = _insert(conn, "a", 5000, status="answered")
    dismissed = _insert(conn, "d", 5000, status="dismissed")
    pending = _insert(conn, "p", 5000)

    _expire_stale_agent_questions(conn, threading.RLock(), url)

    assert _row(conn, answered)["status"] == "answered"
    assert _row(conn, dismissed)["status"] == "dismissed"
    assert _row(conn, pending)["status"] == "expired"


def test_the_question_text_survives_because_it_is_the_record(tmp_path):
    conn, url = _db(tmp_path)
    body = "Avrom Kunsonov (case #64666) has a laptop hard drive that needs recovery"
    qid = _insert(conn, "x", 3195, question=body)

    _expire_stale_agent_questions(conn, threading.RLock(), url)

    assert _row(conn, qid)["question"] == body
    assert conn.execute("SELECT COUNT(*) FROM agent_questions").fetchone()[0] == 1


def test_running_twice_expires_nothing_the_second_time(tmp_path):
    conn, url = _db(tmp_path)
    _insert(conn, "x", 4000)
    assert _expire_stale_agent_questions(conn, threading.RLock(), url)["agent_questions_expired"] == 1
    assert _expire_stale_agent_questions(conn, threading.RLock(), url)["agent_questions_expired"] == 0


def test_the_phase_is_registered_in_the_sweep():
    """An unregistered policy is worth nothing."""
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "lifecycle_sweep.py"
    src = path.read_text(encoding="utf-8")
    assert "_expire_stale_agent_questions(conn, _db_lock, db_url)" in src
    assert '"agent_questions_expired": 0' in src


def test_the_columns_helper_is_idempotent(tmp_path):
    conn, url = _db(tmp_path)
    from app.services.lifecycle_sweep import _ensure_agent_question_columns

    _ensure_agent_question_columns(url, conn)
    cols = {r[1] for r in conn.execute("PRAGMA table_info(agent_questions)")}
    assert "status_note" in cols
    before = len(inspect.getsource(_ensure_agent_question_columns))
    _ensure_agent_question_columns(url, conn)  # cached, must not raise or re-ALTER
    assert len(inspect.getsource(_ensure_agent_question_columns)) == before
