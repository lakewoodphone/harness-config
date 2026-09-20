"""Tests for textstore.py - no network, temp DBs only."""
import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("textstore", HERE.parent / "scripts" / "textstore.py")
textstore = importlib.util.module_from_spec(spec)
spec.loader.exec_module(textstore)


@pytest.fixture()
def conn(tmp_path):
    c = textstore.connect(tmp_path / "inbox.db")
    yield c
    c.close()


def test_connect_creates_a_new_store(tmp_path):
    p = tmp_path / "nested" / "inbox.db"
    c = textstore.connect(p)
    assert p.exists()
    assert c.row_factory is sqlite3.Row
    c.close()


def test_schema_creation_is_idempotent(conn):
    first = textstore.ensure_schema(conn)
    second = textstore.ensure_schema(conn)
    tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"jobs", "person", "meta"} <= tables
    assert first["version"] == second["version"] == textstore.SCHEMA_VERSION
    # The second run must create nothing new.
    assert second["created"] == []


def test_upsert_person_inserts_then_updates_without_duplicating(conn):
    textstore.upsert_person(conn, "+18482102477", name="Yisroel Weinberg",
                            relationship="friend", source="permissions", confidence=0.9)
    textstore.upsert_person(conn, "+18482102477", name="Yisroel W.")
    rows = conn.execute("SELECT * FROM person").fetchall()
    assert len(rows) == 1
    assert rows[0]["name"] == "Yisroel W."
    assert rows[0]["relationship"] == "friend"      # not blanked by the second call
    assert rows[0]["first_seen"] <= rows[0]["last_seen"]


def test_upsert_person_requires_a_phone(conn):
    with pytest.raises(ValueError):
        textstore.upsert_person(conn, "")


def test_open_job_and_read_it_back(conn):
    jid = textstore.open_job(conn, "+18482102477", "SM123", "find out if we repair Hi8",
                            task="check the FAQ and the case files")
    assert isinstance(jid, int)
    row = textstore.job_get(conn, jid)
    assert row["state"] == "open"
    assert row["attempts"] == 0
    assert row["claim"].startswith("find out")
    assert [r["id"] for r in textstore.jobs_open(conn)] == [jid]
    assert [r["id"] for r in textstore.jobs_open(conn, "+18482102477")] == [jid]


def test_job_set_rejects_unknown_columns_and_states(conn):
    jid = textstore.open_job(conn, "+15551234567", None, "x")
    with pytest.raises(ValueError):
        textstore.job_set(conn, jid, nonsense="1")
    with pytest.raises(ValueError):
        textstore.job_set(conn, jid, state="finished")


def test_job_sweep_requeues_a_stale_running_job_then_blocks_it(conn):
    jid = textstore.open_job(conn, "+15551234567", None, "look into it")
    textstore.job_set(conn, jid, state="running")
    # Pretend the lease expired an hour ago.
    conn.execute("UPDATE jobs SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (jid,))
    conn.commit()

    first = textstore.job_sweep(conn, lease_minutes=30, max_attempts=3)
    assert first["requeued"] == [jid]
    assert textstore.job_get(conn, jid)["attempts"] == 1
    assert textstore.job_get(conn, jid)["state"] == "open"

    # Two more deaths and it must stop pretending it is still working on it.
    for _ in range(2):
        textstore.job_set(conn, jid, state="running")
        conn.execute("UPDATE jobs SET updated_at='2020-01-01T00:00:00+00:00' WHERE id=?", (jid,))
        conn.commit()
        textstore.job_sweep(conn, lease_minutes=30, max_attempts=3)
    assert textstore.job_get(conn, jid)["state"] == "blocked"


def test_job_sweep_leaves_a_fresh_running_job_alone(conn):
    jid = textstore.open_job(conn, "+15551234567", None, "x")
    textstore.job_set(conn, jid, state="running")
    out = textstore.job_sweep(conn, lease_minutes=30)
    assert out["requeued"] == [] and out["blocked"] == []
    assert textstore.job_get(conn, jid)["state"] == "running"


def test_doctor_flags_a_job_for_a_number_we_never_heard_from(conn):
    textstore.ensure_schema(conn)
    conn.execute("CREATE TABLE messages (sid TEXT PRIMARY KEY, direction TEXT, from_number TEXT,"
                 " to_number TEXT, body TEXT, date_sent TEXT, first_seen TEXT, state TEXT)")
    # One real correspondent exists, so a job for a different number is the anomaly.
    conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,date_sent,"
                 "first_seen,state) VALUES('S1','inbound','+18482102477','+17324447361',"
                 "'hi','2026-09-18T03:29:39+00:00','2026-09-18T03:29:40+00:00','seen')")
    conn.commit()
    textstore.open_job(conn, "+15550000000", None, "phantom promise")
    out = textstore.doctor(conn)
    assert any("no message from them" in p for p in out["problems"])


def test_doctor_is_clean_on_an_empty_store(conn):
    out = textstore.doctor(conn)
    assert out["problems"] == []
