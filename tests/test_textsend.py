#!/usr/bin/env python3
"""Tests for `scripts/textsend.py` - the safe mouth of the AI text line (audit B9).

No network, no real sends, no real store. Twilio and the owner-notify HTTP call
are monkeypatched at the two functions that own them (`_twilio_post`,
`_post_json`), and the store is a real (temporary) SQLite file created from the
SENSOR's own schema - so the `messages` INSERT shape is checked against the real
column list rather than against a mock.

    python -m pytest tests/test_textsend.py -q
"""
from __future__ import annotations

import importlib.util
import sqlite3
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"

OWNER = "+17325691594"      # permissions: Eliyahu (owner), relationship=owner
BROTHER = "+18485257897"    # permissions: Shabsi (brother), allow=auto  <- the test
WEINBERG = "+18482102477"   # permissions: Yisroel Weinberg, allow=queue
LINE = "+17324447361"


def _load(name: str, filename: str):
    spec = importlib.util.spec_from_file_location(name, str(SCRIPTS / filename))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


ts = _load("textsend", "textsend.py")
inbox = _load("sms_inbox_for_tests", "sms-inbox.py")


# --------------------------------------------------------------------------- #
# fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def no_ambient_config(monkeypatch, tmp_path):
    """The default has to be the thing under test, so nothing may leak in from
    this machine's environment or from the app's real `.env`."""
    for k in ("OWNER_PHONE_NUMBER", "TWILIO_PHONE_NUMBER", "TWILIO_ACCOUNT_SID",
              "TWILIO_AUTH_TOKEN", "AITEXT_ALLOW_THIRD_PARTY_SENDS",
              "AITEXT_ALLOW_UNSIGNED", "SMS_INBOX_DB", "SECRETARY_API_BASE",
              "OWNER_NOTIFY_URL", "OWNER_SMS_KILL_SWITCH"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("SMS_INBOX_ENV", str(tmp_path / "_no_such.env"))
    monkeypatch.setattr(inbox, "ENV_FILE", tmp_path / "_no_such.env", raising=False)
    yield


@pytest.fixture
def db(tmp_path):
    """A real store with the sensor's real schema, and the real ledger rows that
    matter (owner, the brother on auto, Weinberg on queue)."""
    path = tmp_path / "inbox.db"
    conn = sqlite3.connect(str(path))
    conn.executescript(inbox.SCHEMA)
    for phone, name, rel, allow in ((OWNER, "Eliyahu (owner)", "owner", "queue"),
                                    (BROTHER, "Shabsi (brother)", "family", "auto"),
                                    (WEINBERG, "Yisroel Weinberg", "former-worker", "queue")):
        conn.execute(
            "INSERT OR REPLACE INTO permissions(phone,name,relationship,allow,note,"
            "learned_from,updated_at) VALUES(?,?,?,?,?,?,?)",
            (phone, name, rel, allow, "", "test", "2026-09-20T00:00:00+00:00"))
    conn.commit()
    yield path
    conn.close()


def cfg_for(db_path, **over) -> dict:
    cfg = {"db_path": str(db_path), "TWILIO_PHONE_NUMBER": LINE,
           "TWILIO_ACCOUNT_SID": "ACtest", "TWILIO_AUTH_TOKEN": "toktest",
           "OWNER_SMS_KILL_SWITCH": str(Path(db_path).parent / "NO_KILL_SWITCH"),
           "OWNER_NOTIFY_URL": "http://127.0.0.1:8002/tools/notify-owner"}
    cfg.update(over)
    return cfg


def rows(db_path, sid=None, limit=50):
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    q = "SELECT * FROM messages"
    args = ()
    if sid:
        q += " WHERE sid=?"
        args = (sid,)
    q += " LIMIT ?"
    out = [dict(r) for r in conn.execute(q, args + (limit,)).fetchall()]
    conn.close()
    return out


class Twilio:
    """Stands in for Twilio's REST API. Records every call, so a test can assert
    that nothing was sent as easily as that something was."""

    def __init__(self, sid="SM_test_1", status="queued"):
        self.calls = []
        self.sid = sid
        self.status = status

    def __call__(self, cfg, acct, tok, payload, **kw):
        self.calls.append(payload)
        return {"sid": self.sid, "status": self.status, "to": payload.get("To")}

    def explode(self, *a, **kw):
        raise AssertionError("no network call was allowed in this test")


def signed(body: str) -> str:
    return body.rstrip() + "\n- Daniel"


def long_body(target=1000) -> str:
    sentence = "The shop opens at twelve thirty and closes at five. "
    body = sentence * 40
    return signed(body[:target].rsplit(" ", 1)[0])


# --------------------------------------------------------------------------- #
# 1. THE GATE - the one rule that overrides everything
# --------------------------------------------------------------------------- #
def test_default_gate_is_closed_even_for_a_ledger_auto_third_party(db, monkeypatch):
    """The brother's ledger row says allow=auto. Without the env var he is still
    denied: the ledger says who we MAY answer, the env var says whether we may
    answer anyone at all, and the default is closed."""
    monkeypatch.setattr(ts, "_twilio_post", Twilio().explode)
    ok, why = ts.can_send_to(BROTHER, {"allow": "auto"}, cfg_for(db))
    assert ok is False
    assert "AITEXT_ALLOW_THIRD_PARTY_SENDS" in why
    assert "CLOSED" in why


def test_default_gate_is_closed_with_no_ledger_at_all(tmp_path):
    ok, why = ts.can_send_to(BROTHER, {"allow": "auto"}, {"db_path": str(tmp_path / "none.db")})
    assert ok is False and "CLOSED" in why


def test_gate_is_closed_when_ctx_is_missing_or_not_a_dict(db):
    for ctx in (None, {}, [], "auto", {"allow": None}):
        ok, why = ts.can_send_to(BROTHER, ctx, cfg_for(db))
        assert ok is False, ctx
        assert isinstance(why, str) and why


def test_gate_opens_for_the_owner_from_the_env(db):
    ok, why = ts.can_send_to(OWNER, {"allow": "queue"}, cfg_for(db, OWNER_PHONE_NUMBER=OWNER))
    assert ok is True and "owner" in why
    # and it stays open with no ctx at all - the owner is not a third party
    assert ts.can_send_to(OWNER, None, cfg_for(db, OWNER_PHONE_NUMBER=OWNER))[0] is True


def test_gate_opens_for_the_owner_from_the_permissions_row(db):
    """No OWNER_PHONE_NUMBER anywhere: the ledger row relationship='owner' is the
    second, and equally explicit, source."""
    ok, why = ts.can_send_to(OWNER, {"allow": "queue"}, cfg_for(db))
    assert ok is True
    assert "permissions row relationship=owner" in why


def test_gate_opens_for_a_third_party_only_with_the_env_var_AND_allow_auto(db, monkeypatch):
    open_cfg = cfg_for(db, AITEXT_ALLOW_THIRD_PARTY_SENDS="1")

    ok, why = ts.can_send_to(BROTHER, {"allow": "auto"}, open_cfg)
    assert ok is True and "allow=auto" in why

    ok, why = ts.can_send_to(BROTHER, {"allow": "queue"}, open_cfg)
    assert ok is False and "'queue'" in why

    ok, why = ts.can_send_to(BROTHER, {"allow": "never"}, open_cfg)
    assert ok is False

    # env var set but no ctx permission at all
    ok, why = ts.can_send_to(WEINBERG, {}, open_cfg)
    assert ok is False

    # ctx says auto, env var absent
    ok, why = ts.can_send_to(BROTHER, {"allow": "auto"}, cfg_for(db))
    assert ok is False


def test_gate_over_the_environment_not_just_config(db, monkeypatch):
    """The env var is the switch the contract names; reading it only from an
    explicitly-passed config would leave the real deployment shut."""
    monkeypatch.setenv("AITEXT_ALLOW_THIRD_PARTY_SENDS", "1")
    monkeypatch.setenv("SMS_INBOX_DB", str(db))
    ok, why = ts.can_send_to(BROTHER, {"allow": "auto"}, None)
    assert ok is True, why


def test_gate_never_raises_on_garbage(db):
    for phone in (None, "", "not-a-number", 0, "   "):
        ok, why = ts.can_send_to(phone, {"allow": "auto"}, cfg_for(db))
        assert ok is False and isinstance(why, str)


# --------------------------------------------------------------------------- #
# 2. the signature (audit B9 / journal L1976)
# --------------------------------------------------------------------------- #
def test_unsigned_body_refused_for_a_third_party(db):
    cfg = cfg_for(db, AITEXT_ALLOW_THIRD_PARTY_SENDS="1")
    res = ts.send(BROTHER, "Sure, we can look at it.", config=cfg, dry_run=True)
    assert res["ok"] is False
    assert "- Daniel" in res["error"]
    assert res["sid"] is None


def test_unsigned_body_allowed_for_the_owner(db):
    cfg = cfg_for(db, OWNER_PHONE_NUMBER=OWNER)
    res = ts.send(OWNER, "Done - the door code is on the fridge.", config=cfg, dry_run=True)
    assert res["ok"] is True and res["dry_run"] is True and res["sid"] is None


def test_unsigned_hatch_opens_it_deliberately(db):
    cfg = cfg_for(db, AITEXT_ALLOW_THIRD_PARTY_SENDS="1", AITEXT_ALLOW_UNSIGNED="1")
    res = ts.send(BROTHER, "Unsigned on purpose.", config=cfg, dry_run=True)
    assert res["ok"] is True


def test_signature_must_be_the_last_line_and_exact(db):
    assert ts.is_signed("hello\n- Daniel") is True
    assert ts.is_signed("hello\n- Daniel\n\n") is True
    assert ts.is_signed("hello\n- Daniel\nsent from my phone") is False
    assert ts.is_signed("hello - Daniel") is False
    assert ts.is_signed("hello\n- daniel") is False
    assert ts.is_signed("") is False


def test_truncation_never_drops_the_signature(db):
    cfg = cfg_for(db, OWNER_PHONE_NUMBER=OWNER)
    res = ts.send(OWNER, long_body(1400), config=cfg, dry_run=True)
    assert res["ok"] is True
    fitted, detail = ts.fit_to_segments(long_body(1400))
    assert fitted.endswith("- Daniel")
    assert len(fitted) <= ts.SOFT_LIMIT
    assert "truncat" in detail


# --------------------------------------------------------------------------- #
# 3. segments
# --------------------------------------------------------------------------- #
def test_a_1000_char_body_is_truncated_at_a_sentence_boundary_and_says_so(db):
    body = long_body(1000)
    assert len(body) > 930, "the fixture must actually be over 6 segments"

    fitted, detail = ts.fit_to_segments(body)
    assert len(fitted) <= 930
    assert fitted.endswith("- Daniel")
    assert "truncated" in detail and str(len(body)) in detail
    head = fitted[: -len("\n- Daniel")].rstrip()
    assert body.startswith(head), "truncation must be a prefix, not a rewrite"
    assert head.endswith("."), "cut at a sentence boundary"

    # and the same thing is reported through send()
    res = ts.send(OWNER, body, config=cfg_for(db, OWNER_PHONE_NUMBER=OWNER), dry_run=True)
    assert res["ok"] is True
    assert "truncated" in res["detail"] and "930" in res["detail"]


def test_a_short_body_is_untouched():
    body = signed("Hi, this is Daniel from Lakewood Phone & Tech.")
    fitted, detail = ts.fit_to_segments(body)
    assert fitted == body and detail == ""


def test_a_body_at_the_1600_hard_cap_is_still_fitted():
    fitted, detail = ts.fit_to_segments("x" * 2000 + "\n- Daniel")
    assert len(fitted) <= 1600
    assert "truncated" in detail


# --------------------------------------------------------------------------- #
# 4. dry run is the default, and it sends nothing
# --------------------------------------------------------------------------- #
def test_dry_run_default_sends_nothing_at_all(db, monkeypatch):
    tw = Twilio()
    monkeypatch.setattr(ts, "_twilio_post", tw.explode)  # any call is a failure
    res = ts.send(OWNER, signed("Hi."), config=cfg_for(db, OWNER_PHONE_NUMBER=OWNER))
    assert res["ok"] is True
    assert res["dry_run"] is True and res["sid"] is None
    assert "DRY RUN" in res["detail"]
    assert rows(db) == []


def test_a_live_send_records_the_row_and_returns_the_sid(db, monkeypatch):
    tw = Twilio(sid="SM_live_1", status="queued")
    monkeypatch.setattr(ts, "_twilio_post", tw)
    body = signed("Hi, this is Daniel from Lakewood Phone & Tech. Want us to go ahead?")
    res = ts.send(OWNER, body, config=cfg_for(db, OWNER_PHONE_NUMBER=OWNER), dry_run=False)

    assert res["ok"] is True and res["sid"] == "SM_live_1"
    assert res["channel"] == "twilio-ai-line" and res["dry_run"] is False
    assert tw.calls[0]["From"] == LINE and tw.calls[0]["To"] == OWNER
    assert tw.calls[0]["Body"] == body

    got = rows(db, sid="SM_live_1")
    assert len(got) == 1
    r = got[0]
    # the same column list send-from-ai-line.py writes
    assert r["direction"] == "outbound"
    assert r["from_number"] == LINE and r["to_number"] == OWNER
    assert r["body"].endswith("- Daniel")
    assert r["status"] == "queued" and r["state"] == "answered"
    assert r["decided_by"] == "textsend" and r["app_has_it"] is None


def test_a_live_send_to_a_third_party_is_blocked_by_default(db, monkeypatch):
    tw = Twilio()
    monkeypatch.setattr(ts, "_twilio_post", tw.explode)
    res = ts.send(BROTHER, signed("Hi."), config=cfg_for(db), dry_run=False)
    assert res["ok"] is False
    assert "gate closed" in res["error"]
    assert rows(db) == []


def test_send_re_checks_the_gate_even_when_the_caller_forgot(db, monkeypatch):
    """send() does not take a ctx, so it resolves the ledger itself. A caller
    that skips can_send_to must not be able to speak to a third party."""
    tw = Twilio()
    monkeypatch.setattr(ts, "_twilio_post", tw.explode)

    # ledger says auto and the env var is on -> allowed
    tw2 = Twilio(sid="SM_ok")
    monkeypatch.setattr(ts, "_twilio_post", tw2)
    cfg = cfg_for(db, AITEXT_ALLOW_THIRD_PARTY_SENDS="1")
    res = ts.send(BROTHER, signed("Hi."), config=cfg, dry_run=False)
    assert res["ok"] is True and res["sid"] == "SM_ok"

    # same call, env var off -> refused before any network call
    monkeypatch.setattr(ts, "_twilio_post", tw.explode)
    res = ts.send(BROTHER, signed("Hi."), config=cfg_for(db), dry_run=False)
    assert res["ok"] is False


def test_send_without_credentials_fails_as_a_value(db, monkeypatch):
    monkeypatch.setattr(ts, "_twilio_post", Twilio().explode)
    cfg = cfg_for(db, OWNER_PHONE_NUMBER=OWNER)
    cfg.pop("TWILIO_ACCOUNT_SID")
    cfg.pop("TWILIO_AUTH_TOKEN")
    res = ts.send(OWNER, signed("Hi."), config=cfg, dry_run=False)
    assert res["ok"] is False and "credentials" in res["error"]


def test_send_reports_a_transport_failure_as_a_value(db, monkeypatch):
    def boom(*a, **k):
        raise OSError("connection refused")
    monkeypatch.setattr(ts, "_twilio_post", boom)
    res = ts.send(OWNER, signed("Hi."), config=cfg_for(db, OWNER_PHONE_NUMBER=OWNER),
                  dry_run=False)
    assert res["ok"] is False and "connection refused" in res["error"]


def test_send_normalises_the_number_and_the_line():
    assert ts.sender_number({"TWILIO_PHONE_NUMBER": "7324447361"}) == LINE
    assert ts.sender_number({}) == LINE  # the built-in default


# --------------------------------------------------------------------------- #
# 5. owner notify - NOT an SMS
# --------------------------------------------------------------------------- #
def test_notify_owner_dry_run_sends_nothing(db, monkeypatch):
    monkeypatch.setattr(ts, "_notify_post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("no HTTP")))
    res = ts.notify_owner("test string", config=cfg_for(db))
    assert res["ok"] is True and res["dry_run"] is True
    assert "DRY RUN" in res["detail"]
    assert "/tools/notify-owner" in res["detail"]


def test_notify_owner_posts_to_the_app_endpoint(db, monkeypatch):
    seen = {}

    def fake(url, message, **kw):
        seen["url"] = url
        seen["message"] = message
        return 200, "form", '{"ok":true,"suppressed":true,"queue_id":7}'

    monkeypatch.setattr(ts, "_notify_post", fake)
    res = ts.notify_owner("hello owner", config=cfg_for(db), dry_run=False)

    assert res["ok"] is True
    assert res["channel"] == "owner-notify"
    assert res["sid"] is None
    assert seen["url"] == "http://127.0.0.1:8002/tools/notify-owner"
    assert seen["message"] == "hello owner"
    assert "HTTP 200" in res["detail"] and "form-encoded" in res["detail"]
    assert "queue_id" in res["detail"]      # the app's own receipt is reported
    assert "No SMS involved" in res["detail"]


def test_notify_post_tries_json_then_form_because_the_route_is_form_encoded(monkeypatch):
    """The contract says JSON; the deployed route is `message: str = Form(...)`.
    A 422 creates nothing, so retrying with the other encoding cannot notify
    twice - and the encoding that worked is returned for the log."""
    import io
    import urllib.error

    sent = []

    class FakeResponse:
        status = 200

        def read(self):
            return b'{"ok":true,"queue_id":11}'

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

    def fake_urlopen(req, timeout=None):
        ctype = req.get_header("Content-type")
        sent.append((ctype, req.data.decode()))
        if "json" in ctype:
            raise urllib.error.HTTPError(req.full_url, 422, "Unprocessable",
                                         None, io.BytesIO(b'{"detail":"form required"}'))
        return FakeResponse()

    monkeypatch.setattr(ts.urllib.request, "urlopen", fake_urlopen)
    status, encoding, body = ts._notify_post("http://x/tools/notify-owner", "hi there")

    assert (status, encoding) == (200, "form")
    assert [c for c, _ in sent] == ["application/json",
                                    "application/x-www-form-urlencoded"]
    assert sent[0][1] == '{"message": "hi there"}'
    assert sent[1][1] == "message=hi+there"
    assert "queue_id" in body


def test_notify_post_does_not_retry_a_dead_app(monkeypatch):
    """A refused connection is not an encoding problem: one attempt, then the
    caller's fallback decision - not two waits on a dead socket."""
    sent = []

    def fake_urlopen(req, timeout=None):
        sent.append(req)
        raise OSError("connection refused")

    monkeypatch.setattr(ts.urllib.request, "urlopen", fake_urlopen)
    with pytest.raises(OSError):
        ts._notify_post("http://x/tools/notify-owner", "hi")
    assert len(sent) == 1


def test_notify_owner_falls_back_to_sms_only_when_the_app_fails_and_no_kill_switch(db, monkeypatch):
    def down(url, message, **kw):
        raise OSError("connection refused")

    monkeypatch.setattr(ts, "_notify_post", down)
    tw = Twilio(sid="SM_owner_1")
    monkeypatch.setattr(ts, "_twilio_post", tw)
    cfg = cfg_for(db, OWNER_PHONE_NUMBER=OWNER)   # kill switch path does not exist

    res = ts.notify_owner("the app is down", config=cfg, dry_run=False)
    assert res["ok"] is True and res["sid"] == "SM_owner_1"
    assert tw.calls[0]["To"] == OWNER
    assert "fell back to Twilio SMS" in res["detail"]
    assert "absent" in res["detail"]


def test_notify_owner_never_smses_while_the_kill_switch_exists(db, monkeypatch):
    """The kill switch is the owner's own hand on this tap (2026-07-14, 28+
    'URGENT' texts). While it exists, no owner SMS from this path at all."""
    ks = Path(db).parent / "OWNER_SMS_KILL_SWITCH"
    ks.write_text("# OWNER SMS KILL SWITCH\n", encoding="utf-8")

    monkeypatch.setattr(ts, "_notify_post",
                        lambda *a, **k: (_ for _ in ()).throw(OSError("down")))
    monkeypatch.setattr(ts, "_twilio_post",
                        lambda *a, **k: (_ for _ in ()).throw(AssertionError("SMS sent!")))
    cfg = cfg_for(db, OWNER_PHONE_NUMBER=OWNER, OWNER_SMS_KILL_SWITCH=str(ks))

    res = ts.notify_owner("urgent!", config=cfg, dry_run=False)
    assert res["ok"] is False
    assert "kill switch" in res["detail"]
    assert res["error"] and "down" in res["error"]


def test_notify_owner_refuses_an_empty_body(db):
    res = ts.notify_owner("   ", config=cfg_for(db), dry_run=False)
    assert res["ok"] is False and "empty" in res["error"]


# --------------------------------------------------------------------------- #
# 6. history
# --------------------------------------------------------------------------- #
def test_history_returns_outbound_newest_first(db):
    conn = sqlite3.connect(str(db))
    for sid, when in (("SM_old", "2026-09-19T10:00:00+00:00"),
                      ("SM_new", "2026-09-20T10:00:00+00:00")):
        conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,"
                     "date_sent,status,first_seen,state) VALUES(?,?,?,?,?,?,?,?,?)",
                     (sid, "outbound", LINE, OWNER, "hi", when, "delivered", when, "answered"))
    conn.execute("INSERT INTO messages(sid,direction,from_number,to_number,body,date_sent,"
                 "first_seen,state) VALUES(?,?,?,?,?,?,?,'new')",
                 ("SM_in", "inbound", BROTHER, LINE, "hey", "2026-09-20T11:00:00+00:00",
                  "2026-09-20T11:00:00+00:00"))
    conn.commit()
    conn.close()

    got = ts.history(str(db), limit=20)
    assert [r["sid"] for r in got] == ["SM_new", "SM_old"]
    assert all(r["direction"] == "outbound" for r in got)
    assert ts.history(str(Path(db).parent / "missing.db")) == []


def test_history_does_not_raise_on_a_schema_less_file(tmp_path):
    p = tmp_path / "empty.db"
    sqlite3.connect(str(p)).close()
    assert ts.history(str(p)) == []
