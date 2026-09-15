"""The owner queue must forget, or nothing in it means anything.

Measured 2026-09-15: 163 undelivered rows, 42 urgent/critical, 40 of those 42
daily briefings from 2026-08-06 onward, and no code anywhere that aged the
table. These tests pin the policy that fixes it.
"""

from __future__ import annotations

import inspect
import pathlib
import sqlite3
import threading
from datetime import datetime, timedelta, timezone

from app.services.lifecycle_sweep import (
    _expire_stale_owner_messages,
    _owner_message_horizon_hours,
)

CREATE = """CREATE TABLE owner_message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body TEXT, reason TEXT, urgency TEXT, status TEXT,
    created_at TEXT, sent_at TEXT, repeat_count INTEGER, last_seen_at TEXT
)"""


def _db(tmp_path, name="q.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute(CREATE)
    conn.commit()
    return conn, f"sqlite:///{path}"


def _insert(conn, reason, age_hours, body, *, urgency="urgent", status="held",
            seen_hours=None):
    now = datetime.now(timezone.utc)
    created = (now - timedelta(hours=age_hours)).isoformat()
    seen = (now - timedelta(hours=seen_hours if seen_hours is not None else age_hours)).isoformat()
    cur = conn.execute(
        "INSERT INTO owner_message_queue "
        "(body, reason, urgency, status, created_at, repeat_count, last_seen_at) "
        "VALUES (?, ?, ?, ?, ?, 1, ?)",
        (body, reason, urgency, status, created, seen),
    )
    conn.commit()
    return int(cur.lastrowid)


def _status(conn, row_id):
    return conn.execute(
        "SELECT status, status_note FROM owner_message_queue WHERE id = ?", (row_id,)
    ).fetchone()


def test_horizon_by_reason():
    assert _owner_message_horizon_hours("owner_briefing_evening") == 36.0
    assert _owner_message_horizon_hours("owner_briefing_morning") == 36.0
    assert _owner_message_horizon_hours("comms_freshness") == 24.0
    assert _owner_message_horizon_hours("urgent_email") == 336.0
    assert _owner_message_horizon_hours("ask_owner") == 168.0
    # Prefix classes carry their own horizon, not the default.
    assert _owner_message_horizon_hours("sync_breaker:ebay_sync") == 24.0
    assert _owner_message_horizon_hours("sync_needs_login:amazon_sync") == 168.0
    # Anything unrecognised gets a week, never immortality.
    assert _owner_message_horizon_hours("something_new") == 168.0
    assert _owner_message_horizon_hours("") == 168.0


def test_stale_briefings_expire_and_the_newest_survives(tmp_path):
    conn, url = _db(tmp_path)
    old = _insert(conn, "owner_briefing_evening", 900, "briefing from five weeks ago")
    yesterday = _insert(conn, "owner_briefing_evening", 40, "briefing from yesterday")
    today = _insert(conn, "owner_briefing_evening", 5, "tonight's briefing")

    counts = _expire_stale_owner_messages(conn, threading.RLock(), url)

    assert counts["owner_messages_expired"] == 2, counts
    assert _status(conn, old)["status"] == "expired"
    assert _status(conn, yesterday)["status"] == "expired"
    assert _status(conn, today)["status"] == "held"
    assert "held longer than 36h" in _status(conn, old)["status_note"]


def test_two_live_briefings_leave_exactly_one(tmp_path):
    conn, url = _db(tmp_path)
    older = _insert(conn, "owner_briefing_morning", 8, "this morning's briefing")
    newer = _insert(conn, "owner_briefing_morning", 2, "a re-issued briefing")

    counts = _expire_stale_owner_messages(conn, threading.RLock(), url)

    assert counts["owner_messages_superseded"] == 1, counts
    assert _status(conn, older)["status"] == "superseded"
    assert "superseded" in _status(conn, older)["status_note"]
    assert _status(conn, newer)["status"] == "held"


def test_a_recurring_condition_is_kept_alive_by_its_last_observation(tmp_path):
    """A sync breaker that keeps firing is live even if the row is old.

    This is the whole reason the clock is last_seen_at and not created_at: an
    old row that was re-observed minutes ago describes a condition that is still
    true today.
    """
    conn, url = _db(tmp_path)
    recurring = _insert(conn, "sync_breaker:ebay_sync", 900, "eBay sync broken",
                        urgency="high", seen_hours=0.5)

    _expire_stale_owner_messages(conn, threading.RLock(), url)

    assert _status(conn, recurring)["status"] == "held"


def test_money_mail_outlives_a_briefing_but_not_forever(tmp_path):
    conn, url = _db(tmp_path)
    live = _insert(conn, "urgent_email", 160, "Bank of America: insufficient funds")
    dead = _insert(conn, "urgent_email", 400, "an old payment notice")

    _expire_stale_owner_messages(conn, threading.RLock(), url)

    assert _status(conn, live)["status"] == "held"
    assert _status(conn, dead)["status"] == "expired"


def test_nothing_is_deleted_and_sent_rows_are_untouched(tmp_path):
    conn, url = _db(tmp_path)
    stale = _insert(conn, "ask_owner", 2600, "CEO needs your input")
    delivered = _insert(conn, "owner_briefing_evening", 900, "delivered briefing",
                        status="sent")
    before = conn.execute("SELECT COUNT(*) FROM owner_message_queue").fetchone()[0]

    _expire_stale_owner_messages(conn, threading.RLock(), url)

    after = conn.execute("SELECT COUNT(*) FROM owner_message_queue").fetchone()[0]
    assert after == before, "ageing must never delete a row"
    body = conn.execute(
        "SELECT body FROM owner_message_queue WHERE id = ?", (stale,)
    ).fetchone()[0]
    assert body == "CEO needs your input", "the body is the record and must survive"
    assert _status(conn, delivered)["status"] == "sent"


def test_a_send_failure_does_not_refresh_the_age_clock():
    """The bug that would have defeated the policy on its first day.

    last_seen_at is the observation clock. record_owner_message_send_failure used
    to write it, so a five-week-old briefing that failed to send looked freshly
    seen and could never expire.
    """
    from app.database import record_owner_message_send_failure

    src = inspect.getsource(record_owner_message_send_failure)
    update = src.split("UPDATE owner_message_queue", 1)[1]
    assert "last_send_error" in update
    assert "last_seen_at" not in update, (
        "a send attempt is not a re-observation; writing last_seen_at here makes "
        "stale owner messages immortal"
    )


def test_the_phase_is_registered_in_the_sweep():
    """An unregistered policy is worth nothing (the budget-extension lesson)."""
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "lifecycle_sweep.py"
    src = path.read_text(encoding="utf-8")
    assert "_expire_stale_owner_messages(conn, _db_lock, db_url)" in src
    assert '"owner_messages_expired": 0' in src
    assert '"owner_messages_superseded": 0' in src
