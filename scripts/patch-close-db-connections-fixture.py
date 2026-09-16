"""Close the SQLite connections a test opened, or the suite leaks a descriptor per database.

Measured 2026-09-15 with a per-test-file descriptor probe over the whole suite:

    open fds at start: 343
    total growth: 8,160 across 199 of 205 test files
    worst: test_tool_contracts +378, test_lpt_analytics +368 (peak 4,250 open fds)

That is app.database's connection cache: one SQLite connection per `(db_url, thread)`, kept for
performance, and every test's `tmp_path` database is a NEW url -- so each file leaks roughly forty
descriptors (a connection plus its WAL and SHM files) and the run only survived because conftest
raises `RLIMIT_NOFILE` to 16384. On the default limit of 1024 the suite died with
`OSError: [Errno 24] Too many open files`, surfacing as `RuntimeError: no running event loop`.

The app already ships `close_db_connections()` for exactly this; the tests never called it. This
fixture does, after every test, so the raise in conftest becomes head-room rather than a crutch.
"""

from __future__ import annotations

import pathlib
import sys

CONFTEST = pathlib.Path.home() / "personal-secretary-mvp" / "tests" / "conftest.py"

FIXTURE = '''

@pytest.fixture(autouse=True)
def _close_cached_db_connections():
    """Give back the SQLite handles a test opened.

    app.database caches one connection per (db_url, thread) and every test's tmp_path database is a
    new url, so without this the suite grows ~40 descriptors per file -- measured 2026-09-15: 8,160
    across 199 of 205 files, peaking at 4,250 open, which is why the default 1024 limit produced
    `[Errno 24] Too many open files` and why conftest has to raise RLIMIT_NOFILE.
    """
    yield
    try:
        from app import database

        database.close_db_connections()
    except Exception:  # noqa: BLE001 - a teardown that fails must not fail the test
        pass
'''


def main() -> int:
    text = CONFTEST.read_text(encoding="utf-8")
    if "_close_cached_db_connections" in text:
        print("REFUSE: already applied")
        return 2
    if "\nimport pytest\n" not in text and "import pytest" not in text:
        print("REFUSE: conftest does not import pytest; inspect by hand")
        return 2
    CONFTEST.write_text(text.rstrip("\n") + "\n" + FIXTURE, encoding="utf-8")
    print(f"WROTE {CONFTEST}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
