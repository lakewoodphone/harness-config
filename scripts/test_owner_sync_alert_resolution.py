"""An alert whose cause is fixed must stop being an alert.

Measured 2026-09-15: amazon_sync and ebay_sync were re-authenticated in the small
hours and ingested real transactions at 04:30; both `urgent` `sync_needs_login`
rows were still `held` and still being counted as owner-attention debt that
afternoon. These tests pin the resolution path.
"""

from __future__ import annotations

import pathlib
import sqlite3
from datetime import datetime, timezone

from app.database import clear_owner_sync_alerts

CREATE = """CREATE TABLE IF NOT EXISTS owner_message_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    body TEXT, reason TEXT, urgency TEXT, status TEXT,
    created_at TEXT, sent_at TEXT, repeat_count INTEGER, last_seen_at TEXT,
    status_note TEXT
)"""


def _db(tmp_path, name="sync-alerts.db"):
    path = tmp_path / name
    conn = sqlite3.connect(str(path))
    conn.execute(CREATE)
    conn.commit()
    conn.close()
    return f"sqlite:///{path}"


def _insert(url, reason, urgency="urgent", status="held", body="x"):
    path = url.replace("sqlite:///", "")
    conn = sqlite3.connect(path)
    cur = conn.execute(
        "INSERT INTO owner_message_queue "
        "(body, reason, urgency, status, created_at, repeat_count) VALUES (?, ?, ?, ?, ?, 1)",
        (body, reason, urgency, status, datetime.now(timezone.utc).isoformat()),
    )
    conn.commit()
    row_id = int(cur.lastrowid)
    conn.close()
    return row_id


def _row(url, row_id):
    path = url.replace("sqlite:///", "")
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT status, status_note FROM owner_message_queue WHERE id = ?", (row_id,)
    ).fetchone()
    conn.close()
    return dict(row)


def test_a_successful_sync_resolves_both_of_its_alerts(tmp_path):
    url = _db(tmp_path)
    needs_login = _insert(url, "sync_needs_login:amazon_sync")
    breaker = _insert(url, "sync_breaker:amazon_sync", urgency="high")

    cleared = clear_owner_sync_alerts(url, "amazon_sync", evidence="3 new transactions")

    assert cleared == 2
    for row_id in (needs_login, breaker):
        row = _row(url, row_id)
        assert row["status"] == "resolved"
        assert "amazon_sync succeeded" in row["status_note"]
        assert "3 new transactions" in row["status_note"]


def test_it_never_touches_another_subsystem_or_another_kind_of_alert(tmp_path):
    url = _db(tmp_path)
    other_sync = _insert(url, "sync_needs_login:ebay_sync")
    briefing = _insert(url, "owner_briefing_evening")
    email = _insert(url, "urgent_email", body="Bank of America: insufficient funds")

    clear_owner_sync_alerts(url, "amazon_sync", evidence="ok")

    assert _row(url, other_sync)["status"] == "held"
    assert _row(url, briefing)["status"] == "held"
    assert _row(url, email)["status"] == "held"


def test_resolving_twice_is_a_no_op(tmp_path):
    url = _db(tmp_path)
    _insert(url, "sync_needs_login:ebay_sync")
    assert clear_owner_sync_alerts(url, "ebay_sync", evidence="ok") == 1
    assert clear_owner_sync_alerts(url, "ebay_sync", evidence="ok") == 0


def test_an_empty_subsystem_name_does_nothing(tmp_path):
    url = _db(tmp_path)
    _insert(url, "sync_needs_login:amazon_sync")
    assert clear_owner_sync_alerts(url, "") == 0
    assert clear_owner_sync_alerts(url, "   ") == 0


def test_the_wiring_is_in_the_one_place_every_sync_outcome_passes():
    """The emitter and the resolver must be bound to the same signal.

    If this call is ever dropped from _record_subsystem, the alert can be raised
    and never cleared again -- which is exactly the state this fix repairs.
    """
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "autopilot.py"
    src = path.read_text(encoding="utf-8")
    assert 'self._resolve_owner_sync_alerts(str(name), detail)' in src
    assert 'def _resolve_owner_sync_alerts(' in src
