"""A proposal that can be neither applied nor dismissed is a log line pretending to be a queue.

Measured 2026-09-15: `evolution_log` held 75 unapplied rows -- 38 duplicate offers on one file, 18
against a vendored `node_modules` path, and ~19 genuine ones -- while `applied` was the only terminal
state. So the review queue a reader saw was 75, the honest number was 19, and the dead 56 could never
leave it. These tests pin the states and the drain.
"""

from __future__ import annotations

import sqlite3

from app import database as db

SCHEMA = """CREATE TABLE evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, change_type TEXT, description TEXT,
    files_changed TEXT, proposal_id TEXT, applied INTEGER, rollback TEXT, created_at TEXT)"""


def _db(tmp_path) -> str:
    path = tmp_path / "evolution.db"
    conn = sqlite3.connect(path.as_posix())
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()
    return f"sqlite:///{path.as_posix()}"


def _rows(url: str) -> list[dict]:
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    conn.row_factory = sqlite3.Row
    out = [dict(r) for r in conn.execute("SELECT * FROM evolution_log ORDER BY id")]
    conn.close()
    return out


def test_a_new_offer_is_recorded_open(tmp_path):
    url = _db(tmp_path)
    db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"])

    assert _rows(url)[0]["status"] == "open"


def test_an_application_is_recorded_applied(tmp_path):
    url = _db(tmp_path)
    db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], applied=True)

    assert _rows(url)[0]["status"] == "applied"


def test_the_columns_are_added_lazily_and_migration_fills_existing_rows(tmp_path):
    url = _db(tmp_path)
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    conn.execute(
        "INSERT INTO evolution_log (agent_id, change_type, description, files_changed, applied, created_at) "
        "VALUES ('orchestrator','proposal','old','[\"a.py\"]',1,'2026-09-01')"
    )
    conn.execute(
        "INSERT INTO evolution_log (agent_id, change_type, description, files_changed, applied, created_at) "
        "VALUES ('orchestrator','proposal','older','[\"b.py\"]',0,'2026-09-01')"
    )
    conn.commit()
    conn.close()

    db._ensure_evolution_columns(url, db._get_conn(url))

    rows = _rows(url)
    assert rows[0]["status"] == "applied" and rows[1]["status"] == "open"


def test_a_vendored_offer_is_dismissed_with_a_reason(tmp_path):
    url = _db(tmp_path)
    db.log_evolution(url, "proposal", "Bump flatted", ["web/node_modules/x/index.js"])  # refused, no row
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    conn.execute(
        "INSERT INTO evolution_log (agent_id, change_type, description, files_changed, applied, created_at) "
        "VALUES ('orchestrator','proposal','legacy vendored','[\"web/node_modules/x/index.js\"]',0,'2026-09-01')"
    )
    conn.commit()
    conn.close()

    counts = db.dismiss_dead_evolution_proposals(url)

    assert counts == {"vendored": 1, "superseded": 0}, counts
    row = _rows(url)[0]
    assert row["status"] == "dismissed"
    assert "vendored" in row["status_note"]


def test_an_older_duplicate_is_dismissed_and_the_newest_stays_open(tmp_path):
    url = _db(tmp_path)
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    for created in ("2026-09-01", "2026-09-02", "2026-09-03"):
        conn.execute(
            "INSERT INTO evolution_log (agent_id, change_type, description, files_changed, applied, created_at) "
            "VALUES ('orchestrator','proposal','same offer','[\"app/services/x.py\"]',0,?)",
            (created,),
        )
    conn.commit()
    conn.close()

    counts = db.dismiss_dead_evolution_proposals(url)

    assert counts == {"vendored": 0, "superseded": 2}, counts
    rows = _rows(url)
    assert [r["status"] for r in rows] == ["dismissed", "dismissed", "open"], rows


def test_the_drain_never_touches_an_application(tmp_path):
    url = _db(tmp_path)
    db.log_evolution(url, "proposal", "applied once", ["app/services/x.py"], applied=True)
    db.log_evolution(url, "proposal", "applied twice", ["app/services/x.py"], applied=True)

    counts = db.dismiss_dead_evolution_proposals(url)

    assert counts == {"vendored": 0, "superseded": 0}, counts
    assert all(r["status"] == "applied" for r in _rows(url))
