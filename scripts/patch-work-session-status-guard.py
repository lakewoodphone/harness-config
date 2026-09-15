#!/usr/bin/env python3
"""Refuse unknown work_sessions.status values, and repair the 39 that got in.

P50 was "37 numeric status rows are test pollution; no guard exists". Measured
2026-09-14 it is 39 rows, and the shape is worse than "test pollution": the
columns are shifted -- status='5', title='5', agent_id='2026-06-27',
steps_completed=4.2, started_at=0 -- so a test inserted them positionally.

The reason they survived three months is the part worth fixing: every sweep and
every count filters on a known status ('active', 'paused', 'completed', 'failed',
'expired', 'cancelled'), so a row with status='5' is invisible to all of them. It
is counted as neither success nor failure and nothing ever revisits it. The guard
belongs where the value is written.
"""

from __future__ import annotations

import json
import os
import pathlib
import shutil
import sqlite3
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

STATUSES = ("active", "cancelled", "completed", "expired", "failed", "paused")

OLD_BLOCK = '''    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status in ("completed", "failed", "cancelled"):
            updates.append("completed_at = ?")
            params.append(now)'''

NEW_BLOCK = '''    if status is not None and status not in _WORK_SESSION_STATUSES:
        # Refuse junk rather than storing it. In June 2026 a test inserted 39 rows
        # with the columns shifted, leaving statuses like '5' and '4.81'. Nothing
        # rejected them, and because every sweep and every count filters on a known
        # status, those rows were invisible to the cleanup that should have caught
        # them: counted as neither success nor failure for three months.
        logging.getLogger(__name__).error(
            "update_work_session(%s): refusing unknown status %r; allowed: %s",
            session_id,
            status,
            ", ".join(sorted(_WORK_SESSION_STATUSES)),
        )
        status = None
    if status is not None:
        updates.append("status = ?")
        params.append(status)
        if status in ("completed", "failed", "cancelled"):
            updates.append("completed_at = ?")
            params.append(now)'''

CONSTANT = '''# The closed set of legal `work_sessions.status` values. Declared here so a
# writer cannot invent one: a status outside this set is invisible to every
# filter in the codebase, which is how 39 junk rows went unnoticed for months.
_WORK_SESSION_STATUSES = frozenset(
    {
        "active",
        "cancelled",
        "completed",
        "expired",
        "failed",
        "paused",
    }
)


def update_work_session('''

TEST = '''"""work_sessions.status is a closed set; the writer must refuse anything else.

39 rows with statuses like '5' and '4.81' sat in the table from June to September
2026. They were invisible to every count and every sweep, because each of those
filters on a known status -- so nothing was ever going to clean them up.
"""

import sqlite3

from app.database import update_work_session

SCHEMA = """
create table work_sessions (
    id integer primary key,
    status text,
    steps_completed integer,
    total_steps integer,
    progress_pct integer,
    context_json text,
    output_log text,
    updated_at text,
    completed_at text
)
"""


def _scratch(tmp_path):
    path = tmp_path / "scratch.db"
    con = sqlite3.connect(path)
    con.executescript(SCHEMA)
    con.execute(
        "insert into work_sessions (id, status, updated_at, output_log) "
        "values (1, 'active', 'x', '')"
    )
    con.commit()
    con.close()
    return str(path)


def _status(path):
    con = sqlite3.connect(path)
    row = con.execute("select status from work_sessions where id = 1").fetchone()
    con.close()
    return row[0]


def test_a_numeric_status_is_refused_not_stored(tmp_path):
    url = _scratch(tmp_path)
    # '5' matches nothing the caller asked to change, so the update is a no-op.
    assert update_work_session(url, 1, status="5") is False
    assert _status(url) == "active"


def test_the_refusal_does_not_block_a_real_change(tmp_path):
    url = _scratch(tmp_path)
    assert update_work_session(url, 1, status="5", output_append="tick") is True
    # status stayed legal while the other field was still written
    assert _status(url) == "active"


def test_a_known_status_is_applied(tmp_path):
    url = _scratch(tmp_path)
    assert update_work_session(url, 1, status="paused") is True
    assert _status(url) == "paused"


def test_every_status_the_code_uses_is_allowed():
    """Test the guard against the real call sites, not against my memory."""
    import re
    from pathlib import Path

    from app.database import _WORK_SESSION_STATUSES

    app_dir = Path(__file__).resolve().parents[1] / "app"
    used = set()
    for path in app_dir.rglob("*.py"):
        text = path.read_text(encoding="utf-8", errors="replace")
        for match in re.finditer(r"update_work_session\\([^)]*?status=\\"([a-z_]+)\\"", text, re.S):
            used.add(match.group(1))
    assert used, "no update_work_session status= call sites found -- the regex is wrong"
    assert used <= _WORK_SESSION_STATUSES, f"these would now be refused: {used - _WORK_SESSION_STATUSES}"
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")

    assert src.count(OLD_BLOCK) == 1, f"status block: {src.count(OLD_BLOCK)}"
    assert "def update_work_session(" in src
    assert "import logging" in src, "database.py has no logging import"
    assert "_WORK_SESSION_STATUSES" not in src

    backup = BACKUPS / f"database.py.{STAMP}.bak"
    if not backup.exists():
        shutil.copy("app/database.py", backup)

    src = src.replace(OLD_BLOCK, NEW_BLOCK)
    src = src.replace("def update_work_session(", CONSTANT, 1)
    db.write_text(src, encoding="utf-8")
    print("patched app/database.py")

    test = pathlib.Path("tests/test_work_session_status.py")
    test.write_text(TEST, encoding="utf-8")
    print("wrote tests/test_work_session_status.py")

    # ── repair the 39 rows, after exporting them ──────────────────────────
    con = sqlite3.connect("data/secretary.db")
    con.row_factory = sqlite3.Row
    rows = [
        dict(r)
        for r in con.execute(
            "select * from work_sessions where status not in "
            "('completed','failed','paused','active','expired','cancelled')"
        )
    ]
    if not rows:
        print("no polluted rows to repair")
        return 0

    export = BACKUPS / f"work_sessions-junk-status.{STAMP}.json"
    export.write_text(json.dumps(rows, indent=2, default=str), encoding="utf-8")
    print(f"exported {len(rows)} rows -> {export}")

    note = (
        "\\n[REPAIRED 2026-09-14: status was a shifted column from a positional test "
        "insert (status/title held a step number, agent_id held a date, started_at "
        "was 0). It matched no status filter, so no sweep could ever see it. Marked "
        "expired; the original row is in .runtime/deploy-backups.]"
    )
    ids = [r["id"] for r in rows]
    con.execute(
        "update work_sessions set status = 'expired', "
        "output_log = coalesce(output_log, '') || ? "
        f"where id in ({','.join('?' * len(ids))})",
        [note, *ids],
    )
    con.commit()
    left = con.execute(
        "select count(*) from work_sessions where status not in "
        "('completed','failed','paused','active','expired','cancelled')"
    ).fetchone()[0]
    print(f"repaired {len(ids)} rows; remaining with an unknown status: {left}")
    print("status counts now:", dict(con.execute("select status, count(*) from work_sessions group by 1")))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
