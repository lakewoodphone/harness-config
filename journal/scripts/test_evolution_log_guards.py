"""The evolution log must not record the same offer twice, nor any vendored target.

Measured 2026-09-15 in the authoritative database:

    unapplied, last 7 days:  18 rows  ["app/services/activity_sync.py"]
                              8 rows  ["web/node_modules/flatted/python/flatted.py"]
    the first target, all unapplied: 38 rows, ONE distinct description, 38 proposal_ids
    node_modules rows, all time: 19

So the engine mints a new `proposal_id` for a change it has already offered, and the kernel's
`check_evolution` has read HIGH for weeks on exactly that. These tests pin the two guards at the
single writer.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

from app import database as db

SCHEMA = """CREATE TABLE evolution_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT, agent_id TEXT, change_type TEXT, description TEXT,
    files_changed TEXT, proposal_id TEXT, applied INTEGER, rollback TEXT, created_at TEXT)"""


def _db(tmp_path) -> str:
    path: Path = tmp_path / "evolution.db"
    conn = sqlite3.connect(path.as_posix())
    conn.execute(SCHEMA)
    conn.commit()
    conn.close()
    return f"sqlite:///{path.as_posix()}"


def _rows(url: str) -> list[dict]:
    conn = sqlite3.connect(url.replace("sqlite:///", ""))
    conn.row_factory = sqlite3.Row
    rows = [dict(r) for r in conn.execute("SELECT * FROM evolution_log ORDER BY id")]
    conn.close()
    return rows


def test_an_identical_unapplied_offer_is_recorded_once(tmp_path):
    url = _db(tmp_path)
    first = db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], proposal_id="p1")
    second = db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], proposal_id="p2")
    third = db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], proposal_id="p3")

    assert first == second == third, "a re-offer must return the existing row, not add one"
    assert len(_rows(url)) == 1


def test_a_different_description_is_a_different_offer(tmp_path):
    """The description is what makes two offers the same change; dedup must not swallow real ones."""
    url = _db(tmp_path)
    a = db.log_evolution(url, "proposal", "Improve x.py: split long functions", ["app/services/x.py"])
    b = db.log_evolution(url, "proposal", "Improve x.py: add error handling", ["app/services/x.py"])

    assert a != b
    assert len(_rows(url)) == 2


def test_a_vendored_target_is_never_logged(tmp_path):
    url = _db(tmp_path)
    recorded = db.log_evolution(
        url, "proposal", "Bump flatted", ["web/node_modules/flatted/python/flatted.py"]
    )

    assert recorded == 0, "a proposal against a vendored file must not be recorded"
    assert _rows(url) == []


def test_a_mixed_offer_keeps_its_source_target(tmp_path):
    url = _db(tmp_path)
    row_id = db.log_evolution(
        url,
        "proposal",
        "Touch two trees",
        ["app/services/y.py", "web/node_modules/z/index.js"],
    )

    assert row_id
    rows = _rows(url)
    assert rows[0]["files_changed"] == '["app/services/y.py"]', rows[0]["files_changed"]


def test_an_application_is_a_fact_and_is_always_recorded(tmp_path):
    """Two identical applications are two events, not a duplicate offer."""
    url = _db(tmp_path)
    a = db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], applied=True)
    b = db.log_evolution(url, "proposal", "Improve x.py", ["app/services/x.py"], applied=True)

    assert a != b
    assert len(_rows(url)) == 2
    assert all(r["applied"] == 1 for r in _rows(url))


def test_vendored_paths_are_recognised_by_directory(tmp_path):
    for path in (
        "web/node_modules/x/index.js",
        "app/__pycache__/x.pyc",
        ".venv/lib/python3.14/site-packages/x.py",
        "web/.next/server/page.js",
        "C:\\repo\\node_modules\\a\\b.js",
    ):
        assert db._is_vendored_path(path), path
    for path in ("app/services/x.py", "web/app/page.tsx", "docs/notes.md"):
        assert not db._is_vendored_path(path), path
