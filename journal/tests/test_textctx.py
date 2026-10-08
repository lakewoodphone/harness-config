#!/usr/bin/env python3
"""Tests for `textctx` - who is this, and what is going on?

No network. The store and the app DB are built in tmp_path and everything remote is
monkeypatched, because the point of these tests is the module's *behaviour* on a
missing or dead source, and you cannot get a live app to fail on demand.

Definition of done covered here:
  * the full documented shape against a temp store (field for field)
  * a missing app DB is `ok: False` for that source while `permissions` identity survives
  * `render` respects its byte budget
  * `owner_state` returns `{}` when HTTP fails (the URL opener is replaced)
  * plus: the module is a pure reader, and comms never becomes identity.

Run:  python -m pytest tests/test_textctx.py -q
      (add --basetemp=C:\\Users\\ezabz\\code\\_fleet3\\tmp\\ctx if pytest complains about tmp dirs)
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load():
    """Import `scripts/textctx.py` (and its sibling `textstore`) by path.

    `scripts/` is not a package and the two modules import each other by bare name,
    so the directory goes on sys.path rather than using a dotted import.
    """
    sys.path.insert(0, str(REPO / "scripts"))
    spec = importlib.util.spec_from_file_location("textctx", REPO / "scripts" / "textctx.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["textctx"] = mod
    spec.loader.exec_module(mod)
    return mod


ctx = _load()

PHONE = "+18482102477"
TAIL = "8482102477"

PERMISSION_ROW = (PHONE, "Yisroel Weinberg", "friend", "auto",
                  "asked for his wife's business name", "owner", "2026-09-18T02:20:27+00:00")

# (sid, direction, from, to, body, date_sent, state)
MESSAGES = [
    ("SM1", "inbound", PHONE, "+17324447361", "can you look into the whatsapp link", "Fri, 12 Sep 2026 03:03:00 +0000", "queued"),
    ("SM2", "outbound", "+17324447361", PHONE, "on it", "Fri, 12 Sep 2026 04:00:00 +0000", "answered"),
    ("SM3", "inbound", PHONE, "+17324447361", "Don't spend too much time on it", "Fri, 18 Sep 2026 03:03:00 +0000", "queued"),
    ("SM4", "inbound", PHONE, "+17324447361", "any update?", "Fri, 18 Sep 2026 03:29:39 +0000", "new"),
    ("SM5", "inbound", "+18483897895", "+17324447361", "different person entirely", "Fri, 18 Sep 2026 05:00:00 +0000", "new"),
]


def _make_store(path: Path) -> Path:
    """The real store shape: `textstore` owns schema, the sensor owns messages."""
    conn = ctx.textstore.connect(path)
    ctx.textstore.ensure_schema(conn)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS messages (
            sid TEXT PRIMARY KEY, direction TEXT NOT NULL, from_number TEXT NOT NULL,
            to_number TEXT NOT NULL, body TEXT NOT NULL DEFAULT '', date_sent TEXT,
            status TEXT, num_media INTEGER DEFAULT 0, price TEXT, first_seen TEXT NOT NULL,
            app_has_it INTEGER, state TEXT NOT NULL DEFAULT 'new', decided_by TEXT,
            decided_at TEXT, reason TEXT, reply_sid TEXT);
        CREATE TABLE IF NOT EXISTS permissions (
            phone TEXT PRIMARY KEY, name TEXT, relationship TEXT, allow TEXT NOT NULL,
            note TEXT DEFAULT '', learned_from TEXT DEFAULT '', updated_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO permissions VALUES (?,?,?,?,?,?,?)", PERMISSION_ROW)
    for m in MESSAGES:
        conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,date_sent,"
                     "first_seen,state) VALUES(?,?,?,?,?,?,?,'new')",
                     (m[0], m[1], m[2], m[3], m[4], m[5], "2026-09-20T00:00:00+00:00"))
    conn.commit()
    conn.close()
    return path


def _make_app(path: Path) -> Path:
    """The app DB's four tables, with the columns the live ones actually have."""
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE contacts (id INTEGER PRIMARY KEY, name TEXT, phone TEXT, email TEXT,
            address TEXT, company TEXT, role TEXT, notes TEXT, tags_json TEXT, favorite INTEGER,
            created_at TEXT, updated_at TEXT, last_interaction TEXT, interaction_count INTEGER,
            relationship TEXT, source TEXT);
        CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, asked_at TEXT, question TEXT,
            context TEXT, options_json TEXT, recommendation TEXT, severity TEXT, blocks TEXT,
            source TEXT, age_days INTEGER, status TEXT, answered_at TEXT, answer TEXT,
            resolved_at TEXT, resolution TEXT);
        CREATE TABLE dialpad_sms_cache (id INTEGER PRIMARY KEY, session_id TEXT, message_id TEXT,
            phone_normalized TEXT, customer_name TEXT, channel TEXT, direction TEXT,
            created_at TEXT, body_text TEXT, fetched_at TEXT);
        CREATE TABLE dialpad_call_full (call_id TEXT PRIMARY KEY, direction TEXT, state TEXT,
            external_number TEXT, internal_number TEXT, contact_phone TEXT, contact_name TEXT,
            contact_id TEXT, target_id TEXT, target_type TEXT, target_name TEXT, group_id TEXT,
            date_started_ms INTEGER, date_rang_ms INTEGER, date_connected_ms INTEGER,
            date_ended_ms INTEGER, event_timestamp_ms INTEGER, duration_seconds REAL,
            total_duration_seconds REAL, is_transferred INTEGER, was_recorded INTEGER,
            mos_score REAL, recording_url TEXT, admin_recording_urls TEXT, call_recording_ids TEXT,
            recording_details TEXT, voicemail_link TEXT, voicemail_recording_id TEXT,
            transcription_text TEXT, operator_call_id TEXT, entry_point_call_id TEXT,
            entry_point_target TEXT, proxy_target TEXT, raw_payload TEXT, fetched_at TEXT,
            updated_at TEXT);
    """)
    # A contact stored without the +1 prefix, which is the shape that used to be missed.
    conn.execute("INSERT INTO contacts(name,phone,relationship,tags_json) VALUES(?,?,?,?)",
                 ("Weinberg", TAIL, "", '["google-import:eliyahuzabrowsky@gmail.com"]'))
    conn.execute("INSERT INTO owner_decision_queue(asked_at,question,status,severity) VALUES(?,?,?,?)",
                 ("2026-09-20T12:00:00+00:00",
                  f"Yisroel Weinberg ({TAIL}) asked for the sign-up link - send it or hold?", "pending", "normal"))
    conn.execute("INSERT INTO owner_decision_queue(asked_at,question,status) VALUES(?,?,?)",
                 ("2026-09-20T12:00:00+00:00", "Unrelated question about DRN lines", "pending"))
    conn.execute("INSERT INTO dialpad_sms_cache(phone_normalized,customer_name,created_at) VALUES(?,?,?)",
                 (PHONE, "Weinberg soldering guy", "2026-09-19T10:00:00+00:00"))
    conn.execute("INSERT INTO dialpad_call_full(call_id,contact_phone,contact_name,event_timestamp_ms) "
                 "VALUES(?,?,?,?)", ("C1", PHONE, "Weinberg soldering guy", 1789000000000))
    conn.commit()
    conn.close()
    return path


@pytest.fixture()
def store(tmp_path) -> Path:
    return _make_store(tmp_path / "inbox.db")


@pytest.fixture()
def appdb(tmp_path) -> Path:
    return _make_app(tmp_path / "secretary.db")


@pytest.fixture()
def offline(monkeypatch):
    """No HTTP anywhere: every owner endpoint is a dead socket."""
    def boom(*a, **k):
        raise OSError("connection refused (test)")
    monkeypatch.setattr(ctx.urllib.request, "urlopen", boom)


@pytest.fixture()
def wired(monkeypatch, store, appdb, offline):
    """A store + app DB + no network, which is the shape every test below wants."""
    monkeypatch.setenv("SECRETARY_DB", str(appdb))
    return store


# --------------------------------------------------------------------------- #
# 1. the documented shape
# --------------------------------------------------------------------------- #
def test_resolve_returns_the_documented_shape(wired):
    got = ctx.resolve(wired, PHONE)

    assert set(got) >= {"phone", "e164_ok", "identity", "allow", "known", "history",
                        "thread", "open_jobs", "open_owner_rows", "sources", "warnings", "as_of"}
    assert got["phone"] == PHONE
    assert got["e164_ok"] is True

    ident = got["identity"]
    assert set(ident) == {"name", "relationship", "confidence", "source", "aliases"}
    assert ident["name"] == "Yisroel Weinberg"
    assert ident["source"] == "permissions"
    assert ident["confidence"] == 0.95

    assert got["allow"] == "auto"
    assert got["known"] is True

    hist = got["history"]
    assert hist["inbound"] == 3
    assert hist["outbound"] == 1
    assert hist["last_inbound"] == "Fri, 18 Sep 2026 03:29:39 +0000"
    assert hist["last_outbound"].startswith("Fri, 12 Sep 2026")
    # Exactly one inbound (SM1) has a reply after it: SM3/SM4 came 6 days later and
    # nothing followed them. `answered_share` is computed in time order, not by eye.
    assert hist["answered_share"] == pytest.approx(1 / 3)
    # Measured from the wall clock, because that is the only anchor that actually
    # measures staleness (the fixture's messages are in the past, so this is > 0).
    assert hist["days_since_contact"] is not None
    assert hist["days_since_contact"] > 0
    # And the store's own freshness is reported separately, never conflated with it.
    assert "lag_days" in got["store_freshness"]

    # The thread is oldest-first, capped, and only this person's turns.
    assert [t["who"] for t in got["thread"]] == ["them", "us", "them", "them"]
    assert got["thread"][0]["body"] == "can you look into the whatsapp link"
    assert all(t["body"] != "different person entirely" for t in got["thread"])
    assert all(len(t["body"]) <= ctx.BODY_CAP for t in got["thread"])

    for key in ("permissions", "person", "contacts", "comms", "messages", "queue",
                "owner_state", "owner_profile", "jobs"):
        assert key in got["sources"], f"missing provenance for {key}"
        entry = got["sources"][key]
        assert "ok" in entry
        assert entry.get("at") or entry.get("error")
    assert got["sources"]["permissions"]["ok"] is True
    assert got["sources"]["contacts"]["ok"] is True
    assert got["sources"]["comms"]["ok"] is True
    assert got["sources"]["owner_state"]["ok"] is False   # the offline fixture
    assert got["warnings"], "a dead source with no warning is a silent lie"
    assert got["as_of"]

    # `person` and `jobs` are created by textstore.ensure_schema; both empty here.
    assert got["open_jobs"] == []
    assert got["sources"]["person"]["ok"] is True
    assert got["sources"]["person"].get("matched") is not True


def test_thread_is_capped_at_ten_turns_and_300_chars(tmp_path, monkeypatch, offline):
    path = _make_store(tmp_path / "many.db")
    conn = ctx.textstore.connect(path)
    for i in range(14):
        # Dated *after* the seeded messages, so "the newest N" is unambiguous.
        conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,date_sent,"
                     "first_seen,state) VALUES(?,?,?,?,?,?,?,'new')",
                     (f"L{i}", "inbound", PHONE, "+17324447361", "x" * 900,
                      f"Fri, 19 Sep 2026 03:{i:02d}:00 +0000", "2026-09-20T00:00:00+00:00"))
    conn.commit()
    conn.close()
    monkeypatch.setenv("SECRETARY_DB", str(tmp_path / "missing-app.db"))
    got = ctx.resolve(path, PHONE)
    assert len(got["thread"]) <= 10
    assert all(len(t["body"]) <= 300 for t in got["thread"])
    # Newest last, oldest first, and only the newest `THREAD_TURNS` turns.
    assert got["thread"][-1]["sid"] == "L13"
    assert got["thread"][0]["sid"] == f"L{14 - ctx.THREAD_TURNS}"   # "L6" at 8 turns
    assert len(got["thread"]) == ctx.THREAD_TURNS
    assert [t["at"] for t in got["thread"]] == sorted(t["at"] for t in got["thread"])


# --------------------------------------------------------------------------- #
# 2. one dead source never costs the others
# --------------------------------------------------------------------------- #
def test_missing_app_db_is_recorded_but_identity_survives(store, monkeypatch, offline):
    monkeypatch.setenv("SECRETARY_DB", str(store.parent / "does-not-exist.db"))
    got = ctx.resolve(store, PHONE)

    for key in ("contacts", "comms", "queue"):
        assert got["sources"][key]["ok"] is False
        assert got["sources"][key]["error"], "a failed source must say why"
    assert got["identity"]["name"] == "Yisroel Weinberg", "the ledger must not be lost"
    assert got["identity"]["source"] == "permissions"
    assert got["allow"] == "auto"
    assert got["history"]["inbound"] == 3
    assert any("app DB" in w for w in got["warnings"])
    assert got["open_owner_rows"] == []


def test_no_app_db_env_at_all_still_resolves(store, monkeypatch, offline):
    monkeypatch.delenv("SECRETARY_DB", raising=False)
    monkeypatch.setattr(ctx, "DEFAULT_APP_DB", str(store.parent / "nope.db"))
    got = ctx.resolve(store, PHONE)
    assert got["identity"]["name"] == "Yisroel Weinberg"
    assert got["sources"]["contacts"]["ok"] is False


def test_missing_person_table_is_ok_false_not_a_crash(tmp_path, monkeypatch, offline):
    """The live store on 2026-09-20 had no `person` table at all."""
    path = tmp_path / "bare.db"
    conn = sqlite3.connect(path)
    conn.executescript("""
        CREATE TABLE messages (sid TEXT PRIMARY KEY, direction TEXT, from_number TEXT,
            to_number TEXT, body TEXT, date_sent TEXT, state TEXT);
        CREATE TABLE permissions (phone TEXT PRIMARY KEY, name TEXT, relationship TEXT,
            allow TEXT NOT NULL, note TEXT, learned_from TEXT, updated_at TEXT NOT NULL);
    """)
    conn.execute("INSERT INTO permissions VALUES(?,?,?,?,?,?,?)", PERMISSION_ROW)
    conn.execute("INSERT INTO messages VALUES('S1','inbound',?,?,?,'2026-09-18T03:29:39+00:00','new')",
                 (PHONE, "+17324447361", "hello"))
    conn.commit()
    conn.close()
    monkeypatch.setenv("SECRETARY_DB", str(tmp_path / "no-app.db"))

    got = ctx.resolve(path, PHONE)          # textstore.connect() will add person/jobs
    assert got["sources"]["permissions"]["ok"] is True
    assert got["identity"]["name"] == "Yisroel Weinberg"

    # And with textstore's schema deliberately absent, it is `ok: False`, not a raise.
    conn2 = sqlite3.connect(path)
    conn2.close()
    monkeypatch.setattr(ctx, "textstore", None)
    got2 = ctx.resolve(path, PHONE)
    assert got2["sources"]["person"]["ok"] is False
    assert got2["identity"]["name"] == "Yisroel Weinberg"
    assert got2["history"]["inbound"] == 1


def test_resolve_never_raises_on_garbage():
    for bad in (None, "", "not-a-phone", 42, "12345"):
        got = ctx.resolve("C:/definitely/not/here/inbox.db", bad)
        assert isinstance(got, dict)
        assert got["history"]["inbound"] == 0
        assert got["allow"] == "queue"
        assert got["sources"]["permissions"]["ok"] is False


def test_store_freshness_is_not_a_text_max(tmp_path, monkeypatch, offline):
    """`MAX(date_sent)` in SQL sorts by weekday name. Measured 2026-09-20 on the live
    store: it returned `Wed, 29 Jul 2026` while the newest message was
    `Fri, 18 Sep 2026`, making the store look 53 days stale when it was 2."""
    path = _make_store(tmp_path / "textmax.db")
    conn = ctx.textstore.connect(path)
    conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,date_sent,"
                 "first_seen,state) VALUES('NEW','inbound',?,?,?,?,?,'new')",
                 (PHONE, "+17324447361", "newest", "Fri, 18 Sep 2026 03:29:39 +0000",
                  "2026-09-20T00:00:00+00:00"))
    conn.commit()
    conn.close()
    monkeypatch.setenv("SECRETARY_DB", str(tmp_path / "none.db"))
    got = ctx.resolve(path, PHONE)
    newest = got["store_freshness"]["newest"]
    assert ctx.parse_ts(newest) == max(ctx.parse_ts(r[5]) for r in MESSAGES
                                       + [("NEW", "", "", "", "", "Fri, 18 Sep 2026 03:29:39 +0000", "")])
    assert got["store_freshness"]["lag_days"] is not None
    assert got["store_freshness"]["lag_days"] < 30


def test_unknown_number_gets_queue_and_a_warning(store, monkeypatch, offline):
    monkeypatch.setenv("SECRETARY_DB", str(store.parent / "none.db"))
    got = ctx.resolve(store, "+15555550199")
    assert got["allow"] == "queue"          # unknown never means `auto`
    assert got["known"] is False
    assert got["identity"]["name"] is None
    assert any("identity" in w for w in got["warnings"])


# --------------------------------------------------------------------------- #
# 3. comms is context, never identity
# --------------------------------------------------------------------------- #
def test_dialpad_customer_never_becomes_the_identity(wired):
    got = ctx.resolve(wired, PHONE)
    assert got["identity"]["name"] == "Yisroel Weinberg"          # from permissions
    assert got["sources"]["comms"]["ok"] is True
    assert got["sources"]["comms"]["sms"] == 1
    assert got["sources"]["comms"]["calls"] == 1
    assert any("business line" in w for w in got["warnings"])


def test_unidentified_number_takes_the_contacts_name_not_the_dialpad_one(store, appdb, monkeypatch, offline):
    """`+18482245096` is literally `unknown (+18482245096)` in the ledger (audit B8)."""
    conn = sqlite3.connect(store)
    conn.execute("INSERT INTO permissions VALUES(?,?,?,?,?,?,?)",
                 ("+18482245096", "unknown (+18482245096)", "unknown", "queue", "", "system",
                  "2026-09-18T02:28:50+00:00"))
    conn.commit()
    conn.close()
    monkeypatch.setenv("SECRETARY_DB", str(appdb))
    got = ctx.resolve(store, "+18482245096")
    assert got["identity"]["name"] is None, "a placeholder is not a name"
    assert got["allow"] == "queue"


def test_open_owner_rows_only_for_this_person(wired):
    got = ctx.resolve(wired, PHONE)
    assert len(got["open_owner_rows"]) == 1
    assert got["open_owner_rows"][0]["id"] == 1
    assert TAIL in got["open_owner_rows"][0]["question"]
    assert got["sources"]["queue"]["ok"] is True


# --------------------------------------------------------------------------- #
# 4. owner_state / owner_profile
# --------------------------------------------------------------------------- #
def test_owner_state_returns_empty_dict_when_http_fails(monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(ctx.urllib.request, "urlopen", boom)
    assert ctx.owner_state() == {}
    assert ctx.owner_profile() == {}


def test_owner_state_unwraps_value_and_profile(monkeypatch):
    class Resp:
        def __init__(self, payload):
            self._payload = json.dumps(payload).encode()

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        url = req.full_url
        if url.endswith("/owner/state"):
            return Resp({"ok": True, "key": "current",
                         "value": {"calendar_inference": {"availability": "available"}},
                         "updated_at": "2026-09-20T16:23:09+00:00"})
        return Resp({"ok": True, "profile": {"spend_approval_threshold": {"value": "always_manual"}}})

    monkeypatch.setattr(ctx.urllib.request, "urlopen", fake_urlopen)
    state = ctx.owner_state()
    assert state["calendar_inference"]["availability"] == "available"
    assert state["updated_at"] == "2026-09-20T16:23:09+00:00"
    assert ctx.owner_profile()["spend_approval_threshold"]["value"] == "always_manual"


def test_owner_state_http_status_error_is_recorded_in_sources(wired, monkeypatch):
    def fake_owner_get(path, timeout):
        return {}, {"ok": False, "at": "2026-09-20T00:00:00+00:00", "url": path,
                    "error": "HTTPError: HTTP Error 404: Not Found"}
    monkeypatch.setattr(ctx, "_owner_get", fake_owner_get)
    got = ctx.resolve(wired, PHONE)
    assert got["sources"]["owner_state"]["ok"] is False
    assert "404" in got["sources"]["owner_state"]["error"]
    assert any("owner_state unreachable" in w for w in got["warnings"])
    assert got["owner_state"] == {}


# --------------------------------------------------------------------------- #
# 5. render
# --------------------------------------------------------------------------- #
def test_render_respects_its_byte_budget(wired):
    got = ctx.resolve(wired, PHONE)
    for budget in (120, 200, 400, 700, 1200, 4000):
        text = ctx.render(got, budget=budget)
        assert isinstance(text, str)
        assert len(text.encode("utf-8")) <= budget, f"budget {budget} exceeded"


def test_render_never_cuts_a_line_in_half(wired):
    got = ctx.resolve(wired, PHONE)
    text = ctx.render(got, budget=900)
    assert "..." not in text
    for line in text.splitlines():
        assert line.strip(), "no blank filler lines"
    assert not text.endswith("| ")


def test_render_names_what_is_not_known(store, monkeypatch, offline):
    monkeypatch.setenv("SECRETARY_DB", str(store.parent / "missing.db"))
    got = ctx.resolve(store, "+15555550199")
    text = ctx.render(got, budget=1200)
    assert "NOT KNOWN:" in text
    assert "contacts" in text and "business-line comms" in text
    assert "WHO" in text and "PERMISSION allow=queue" in text
    assert "THREAD: none" in text


def test_render_includes_allow_history_thread_and_availability(monkeypatch):
    class Resp:
        def __init__(self, payload):
            self._payload = json.dumps(payload).encode()

        def read(self):
            return self._payload

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        if req.full_url.endswith("/owner/state"):
            return Resp({"ok": True, "value": {"calendar_inference": {"availability": "offline",
                                                                     "reason": "shabbos"}}})
        return Resp({"ok": True, "profile": {"x": {"value": "y", "confidence": 1.0}}})

    monkeypatch.setattr(ctx.urllib.request, "urlopen", fake_urlopen)
    got = ctx.resolve("C:/definitely/not/here.db", PHONE)
    got["identity"] = {"name": "Yisroel Weinberg", "relationship": "friend",
                       "confidence": 0.9, "source": "permissions", "aliases": []}
    got["allow"] = "auto"
    got["known"] = True
    got["history"].update({"inbound": 7, "outbound": 6, "last_inbound": "2026-09-18T03:29:39+00:00"})
    got["thread"] = [{"who": "them", "body": "any update?", "at": "2026-09-18T03:29:39+00:00", "sid": "SM4"}]
    text = ctx.render(got, budget=1400)
    assert "Yisroel Weinberg" in text
    assert "relationship=friend" in text
    assert "PERMISSION allow=auto" in text
    assert "HISTORY 7 in / 6 out" in text
    assert "any update?" in text
    assert "OWNER AVAILABILITY offline" in text


def test_render_truncates_from_the_oldest_end(wired):
    got = ctx.resolve(wired, PHONE)
    big = ctx.render(got, budget=4000)
    small = ctx.render(got, budget=700)
    # Whatever survives, the newest turn is kept and the oldest is the first to go.
    assert len(small) <= len(big)
    if got["thread"]:
        assert got["thread"][-1]["body"][:20] in small or "THREAD" not in small


def test_render_survives_a_nonsense_budget(wired):
    got = ctx.resolve(wired, PHONE)
    assert len(ctx.render(got, budget=5).encode()) <= 5
    stub = ctx.render(got, budget=80)
    assert stub and len(stub.encode()) <= 80
    assert "CONTEXT OMITTED" in stub, "a stub must say it is a stub"
    assert len(ctx.render(got, budget=40).encode()) <= 40
    # A zero budget can carry nothing, and an empty string is the honest answer to
    # "send nothing" - it must not raise or invent a line.
    assert ctx.render(got, budget=0) == ""
    assert "NOT KNOWN" in ctx.render(got, budget="nonsense")
    assert ctx.render(None) == "NOT KNOWN: context unavailable (render got no dict)"


# --------------------------------------------------------------------------- #
# 6. purity - it is a reader
# --------------------------------------------------------------------------- #
def test_is_a_pure_reader(tmp_path, monkeypatch, offline):
    path = _make_store(tmp_path / "pure.db")
    app = _make_app(tmp_path / "pure-app.db")
    monkeypatch.setenv("SECRETARY_DB", str(app))
    seen: list[str] = []

    before = (path.read_bytes(), app.read_bytes())

    real_connect = sqlite3.connect

    def traced(database, *a, **k):
        conn = real_connect(database, *a, **k)
        conn.set_trace_callback(lambda stmt: seen.append(str(stmt)))
        return conn

    monkeypatch.setattr(ctx.sqlite3, "connect", traced)
    got = ctx.resolve(path, PHONE)
    assert got["identity"]["name"] == "Yisroel Weinberg"
    writes = [s for s in seen
              if s.strip().split(" ")[0].upper() in ("INSERT", "UPDATE", "DELETE", "DROP",
                                                     "ALTER", "CREATE", "REPLACE", "VACUUM")]
    assert not writes, f"textctx must never write: {writes[:3]}"
    assert (path.read_bytes(), app.read_bytes()) == before


def test_module_has_no_write_statements():
    """No write verb may appear in the module's *SQL* - docstrings and comments say
    the words on purpose, so the check is on every other string literal."""
    import ast
    tree = ast.parse((REPO / "scripts" / "textctx.py").read_text(encoding="utf-8"))
    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            doc = ast.get_docstring(node, clean=False)
            if doc:
                docstrings.add(doc)
    writes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            if node.value in docstrings:
                continue
            head = node.value.strip().split(" ")[0].upper()
            # `replace(...)` is sqlite's string function, not a write verb.
            if head in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "CREATE"):
                writes.append(node.value.strip()[:60])
    assert not writes, f"textctx must contain no write SQL: {writes}"


def test_app_db_is_opened_read_only(tmp_path, monkeypatch, offline):
    app = _make_app(tmp_path / "ro.db")
    monkeypatch.setenv("SECRETARY_DB", str(app))
    conn = ctx._open_ro(app)
    with pytest.raises(sqlite3.OperationalError):
        conn.execute("INSERT INTO contacts(name,phone) VALUES('x','y')")
    conn.close()


def test_data_sources_constant_matches_the_contract():
    assert ctx.DATA_SOURCES == ("contacts", "permissions", "person", "sources", "memory",
                                "owner_state", "queue")
    assert callable(ctx.resolve) and callable(ctx.render)
    assert callable(ctx.owner_state) and callable(ctx.owner_profile)


# --------------------------------------------------------------------------- #
# 7. helpers that other modules depend on
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("raw,key", [
    ("+18482102477", "8482102477"),
    ("18482102477", "8482102477"),
    ("8482102477", "8482102477"),
    ("(848) 210-2477", "8482102477"),
    ("+1 848-210-2477", "8482102477"),
])
def test_norm_matches_the_sensor(raw, key):
    assert ctx.norm(raw) == key


def test_parse_ts_handles_all_three_shapes():
    assert ctx.parse_ts("Fri, 18 Sep 2026 03:29:39 +0000").year == 2026
    assert ctx.parse_ts("2026-09-18T03:29:39+00:00").month == 9
    assert ctx.parse_ts("2026-09-18 03:29:39").day == 18
    assert ctx.parse_ts(1789000000000).year == 2026     # dialpad epoch ms
    assert ctx.parse_ts(None) is None
    assert ctx.parse_ts("not a date") is None
