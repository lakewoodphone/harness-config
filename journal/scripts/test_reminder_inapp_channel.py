"""A due reminder must reach a surface the owner reads, not just a status column.

Measured 2026-09-15 (P148): reminders carry `delivery_channel='dashboard'` by default and
`status='sent'`, while nothing renders them -- `process_due_reminders` skips every channel
that is not sms/both. These tests pin the fix: the in-app channels enqueue into the
owner-message queue (which the badge renders and the shelf life ages), as `held`, so a
reminder can never become an outbound SMS on its own.
"""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

import app.database as database
from app.services.personal_ops import process_due_reminders

OWNER_QUEUE = """CREATE TABLE IF NOT EXISTS owner_message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body TEXT, reason TEXT, urgency TEXT, status TEXT,
    created_at TEXT, sent_at TEXT, repeat_count INTEGER, last_seen_at TEXT
)"""


class _Settings:
    def __init__(self, url: str):
        self.database_url = url


def _db(tmp_path, name="reminders.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.execute(OWNER_QUEUE)
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def _due(delivery_channel, priority="normal", rid=7, message="Health follow-up"):
    return {
        "id": rid,
        "message": message,
        "priority": priority,
        "delivery_channel": delivery_channel,
        "requires_ack": 0,
    }


def _queue_rows(url):
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM owner_message_queue")]
    conn.close()
    return rows


def test_a_dashboard_reminder_reaches_the_owner_queue(tmp_path, monkeypatch):
    url = _db(tmp_path)
    monkeypatch.setattr(database, "list_due_reminders", lambda *a, **k: [_due("dashboard")])
    monkeypatch.setattr(database, "mark_reminder_delivered", lambda *a, **k: True)

    result = process_due_reminders(_Settings(url))

    assert result["checked"] == 1 and result["delivered"] == 1, result
    assert result["queued"] == 1, result
    rows = _queue_rows(url)
    assert len(rows) == 1, rows
    assert rows[0]["reason"] == "reminder:7"
    assert rows[0]["status"] == "held", "a reminder must never become an outbound SMS by itself"
    assert "Reminder: Health follow-up" in rows[0]["body"]


def test_an_urgent_reminder_keeps_its_urgency_and_marker(tmp_path, monkeypatch):
    url = _db(tmp_path)
    monkeypatch.setattr(
        database, "list_due_reminders", lambda *a, **k: [_due("dashboard", priority="urgent")]
    )
    monkeypatch.setattr(database, "mark_reminder_delivered", lambda *a, **k: True)

    process_due_reminders(_Settings(url))

    row = _queue_rows(url)[0]
    assert row["urgency"] == "urgent"
    assert row["body"].startswith("🚨")


def test_the_default_channel_is_the_in_app_one(tmp_path, monkeypatch):
    """An absent channel must mean the surface, not a silent drop."""
    url = _db(tmp_path)
    reminder = _due("")
    reminder.pop("delivery_channel")
    monkeypatch.setattr(database, "list_due_reminders", lambda *a, **k: [reminder])
    monkeypatch.setattr(database, "mark_reminder_delivered", lambda *a, **k: True)

    result = process_due_reminders(_Settings(url))

    assert result["queued"] == 1, result
    assert _queue_rows(url)[0]["reason"] == "reminder:7"


def test_the_same_reminder_twice_does_not_double_queue(tmp_path, monkeypatch):
    """The queue dedups on (reason, body) for undelivered rows, and that must hold here."""
    url = _db(tmp_path)
    monkeypatch.setattr(database, "list_due_reminders", lambda *a, **k: [_due("dashboard")])
    monkeypatch.setattr(database, "mark_reminder_delivered", lambda *a, **k: True)

    process_due_reminders(_Settings(url))
    process_due_reminders(_Settings(url))

    rows = _queue_rows(url)
    assert len(rows) == 1, rows
    assert rows[0]["repeat_count"] == 2, rows


def test_a_reminder_nobody_can_read_is_still_counted_as_queued_not_sent(tmp_path, monkeypatch):
    """`queued` and `delivered` are different facts; the result must say both."""
    url = _db(tmp_path)
    monkeypatch.setattr(database, "list_due_reminders", lambda *a, **k: [_due("app")])
    monkeypatch.setattr(database, "mark_reminder_delivered", lambda *a, **k: True)

    result = process_due_reminders(_Settings(url))

    assert result["delivered"] == 1
    assert result["queued"] == 1
    assert result["sms_sent"] == 0
