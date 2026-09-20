"""Tests for textwork.py - no network, no real tools, no sends."""
import importlib.util
import json
import sqlite3
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("textwork", HERE.parent / "scripts" / "textwork.py")
tw = importlib.util.module_from_spec(spec)
# Register before exec: @dataclass resolves type annotations through
# sys.modules[cls.__module__], and it is None unless the module is registered.
sys.modules["textwork"] = tw
spec.loader.exec_module(tw)


def ctx(phone="+18482102477", name="Yisroel Weinberg", rel="friend"):
    return {"phone": phone, "allow": "queue",
            "identity": {"name": name, "relationship": rel},
            "history": {"inbound": 7, "outbound": 6, "last_inbound": "2026-09-18"},
            "thread": [{"who": "them", "body": "do you fix hi8 players?"}],
            "open_jobs": [], "open_owner_rows": [], "warnings": []}


def llm_sequence(*replies):
    """An injected model that walks a scripted list, then repeats the last reply."""
    state = {"i": 0}
    seen = []

    def _llm(system, user):
        seen.append(user)
        i = min(state["i"], len(replies) - 1)
        state["i"] += 1
        return replies[i]

    _llm.seen = seen
    return _llm


class NoModel:
    last_error = "catalog unreadable: refused"

    def resolve_model(self):
        return None


# ------------------------------------------------------------------ happy path
def test_a_tool_then_an_answer_is_ok(monkeypatch):
    monkeypatch.setattr(tw, "_invoke", lambda tool, args: (True, "we do repair hi8"))
    llm = llm_sequence(
        json.dumps({"tool": "web_search", "args": {"query": "hi8 repair"}, "why": "check"}),
        json.dumps({"answer": "Yes, we do repair Hi8 and Video 8 players.",
                    "evidence": "faq + web"}))
    r = tw.do("find out if we repair hi8", "check the faq", ctx(), llm=llm)
    assert r.ok is True
    assert "Hi8" in r.answer
    assert r.tools_used == ["web_search"]
    assert "web_search" in r.evidence
    assert r.steps == 2


def test_evidence_names_what_was_read_even_without_the_model_saying_so(monkeypatch):
    monkeypatch.setattr(tw, "_invoke", lambda tool, args: (True, "data"))
    llm = llm_sequence(
        json.dumps({"tool": "app_db_query", "args": {"sql": "SELECT 1"}}),
        json.dumps({"answer": "It shipped Tuesday."}))   # no "evidence" field
    r = tw.do("did it ship", "check orders", ctx(), llm=llm)
    assert r.ok is True
    assert "app_db_query" in r.evidence


# ------------------------------------------------------------------ no model
def test_no_model_means_blocked_and_nothing_invented():
    r = tw.do("check something", "check", ctx(), decider=NoModel())
    assert r.ok is False
    assert r.blocked and "no model" in r.blocked
    assert r.answer is None


# ------------------------------------------------------------------ JSON contract
def test_two_bad_json_replies_block_rather_than_guess():
    llm = llm_sequence("I think the answer might be yes", "still not json")
    r = tw.do("check", "check", ctx(), llm=llm)
    assert r.ok is False
    assert "JSON" in (r.blocked or "")
    assert r.answer is None


def test_one_bad_json_reply_gets_a_retry_then_succeeds():
    llm = llm_sequence("prose first", json.dumps({"answer": "Yes, we do."}))
    r = tw.do("check", "check", ctx(), llm=llm)
    assert r.ok is True and r.steps == 2


def test_a_blocked_reply_is_a_result_not_a_failure_to_report(monkeypatch):
    llm = llm_sequence(json.dumps({"blocked": "could not find it anywhere"}))
    r = tw.do("check", "check", ctx(), llm=llm)
    assert r.ok is False
    assert r.blocked == "could not find it anywhere"
    assert r.answer is None


def test_a_block_needing_the_owner_raises_an_escalation():
    llm = llm_sequence(json.dumps(
        {"blocked": "needs the owner: only he can agree a price"}))
    r = tw.do("how much for a screen", "price it", ctx(), llm=llm)
    assert r.ok is False
    assert r.escalated, "a block that needs him must produce a question"
    assert "+18482102477" in r.escalated["question"]


# ------------------------------------------------------------------ budgets
def test_tool_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(tw, "_invoke", lambda tool, args: (True, "x"))
    monkeypatch.setattr(tw, "MAX_STEPS", 50)
    llm = llm_sequence(*[json.dumps({"tool": "web_search", "args": {"query": "q"}})] * 50)
    r = tw.do("loop forever", "loop", ctx(), llm=llm)
    assert r.ok is False
    assert r.blocked
    assert len(r.tools_used) <= tw.MAX_TOOL_CALLS


def test_step_budget_is_enforced(monkeypatch):
    monkeypatch.setattr(tw, "_invoke", lambda tool, args: (True, "x"))
    monkeypatch.setattr(tw, "MAX_STEPS", 2)
    llm = llm_sequence(*[json.dumps({"tool": "web_search", "args": {"query": "q"}})] * 10)
    r = tw.do("keep going", "go", ctx(), llm=llm)
    assert r.ok is False
    assert r.steps <= 2


def test_timeout_is_a_value_not_a_hang(monkeypatch):
    monkeypatch.setattr(tw, "MAX_STEPS", 50)

    def slow(system, user):
        return json.dumps({"tool": "web_search", "args": {"query": "q"}})

    monkeypatch.setattr(tw, "_invoke", lambda tool, args: (True, "x"))
    r = tw.do("never finishes", "go", ctx(), llm=slow, timeout=0)
    assert r.ok is False
    assert r.blocked == "timeout"
    assert r.elapsed_s < 5


# ------------------------------------------------------------------ SQL guard
@pytest.mark.parametrize("sql", [
    "DELETE FROM messages",
    "UPDATE tasks SET x=1",
    "DROP TABLE jobs",
    "INSERT INTO jobs VALUES (1)",
    "PRAGMA table_info(jobs)",
    "  delete from x",
])
def test_app_db_query_refuses_anything_but_select(sql):
    ok, out = tw.tool_app_db_query(sql)
    assert ok is False, sql
    assert "refused" in out


def test_app_db_query_refuses_multiple_statements():
    ok, out = tw.tool_app_db_query("SELECT 1; DELETE FROM messages")
    assert ok is False


def test_app_db_query_reads_a_real_select(tmp_path, monkeypatch):
    db = tmp_path / "app.db"
    c = sqlite3.connect(db)
    c.execute("CREATE TABLE t (a TEXT)")
    c.execute("INSERT INTO t VALUES ('hello')")
    c.commit()
    c.close()
    monkeypatch.setenv("SECRETARY_DB", str(db))
    ok, out = tw.tool_app_db_query("SELECT a FROM t")
    assert ok is True
    assert "hello" in out


def test_app_db_query_reports_a_missing_database_rather_than_raising(monkeypatch, tmp_path):
    # A directory that genuinely does not exist: sqlite would happily CREATE a file at
    # a merely-absent path, so "missing" has to mean an unusable path.
    monkeypatch.setenv("SECRETARY_DB", str(tmp_path / "no_such_dir" / "app.db"))
    ok, out = tw.tool_app_db_query("SELECT 1")
    assert ok is False
    assert "query failed" in out


def test_unknown_tool_is_reported_not_raised():
    ok, out = tw._invoke("no_such_tool", {})
    assert ok is False
    assert "unknown tool" in out


def test_tool_exceptions_become_values(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("kaboom")

    monkeypatch.setattr(tw, "tool_web_search", boom)
    ok, out = tw._invoke("web_search", {"query": "x"})
    assert ok is False
    assert "kaboom" in out


def test_playbooks_are_declared():
    assert len(tw.playbook_titles()) >= 5


def test_dossier_includes_the_person_and_the_thread():
    d = tw._render_dossier("find out about hi8", "check", ctx(), "a text back")
    assert "Yisroel Weinberg" in d
    assert "hi8" in d
    assert "THE JOB" in d
