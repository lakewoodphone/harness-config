#!/usr/bin/env python3
"""Tests for owner-text-audit.py -- no network, no live database, no wake store.

Run with:
    python test-owner-text-audit.py

Every fixture is a temporary SQLite file built from the LIVE `CREATE TABLE`
statements (copied from the authority on 2026-10-18 with
`sqlite3 /root/authority.db '.schema <table>'`, same for relay.db and asks.db),
so a column the audit reads and the schema does not have fails here rather than
on the authority.

The planted conditions are the ones the audit exists to count, including the
live shapes measured on 2026-10-18:
  * the duplicate LOG: two sms_log rows, ONE twilio_sid, 2 s apart
  * the live DOUBLE SEND: two rows, same body, DIFFERENT sids, 0.3 s apart
  * `verdict=SEND, verdict_reason=too-long, status=pending` in relay.attempt
  * a truncated body whose original is still in owner_message_queue
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
SCRIPT = HERE / "owner-text-audit.py"
OWNER = "+18483897895"
FAMILY = "+18482245096"

NOW = datetime.now(timezone.utc).replace(microsecond=0)

PASSED = 0
FAILED: list[str] = []


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASSED
    if condition:
        PASSED += 1
        print(f"  ok   {name}")
    else:
        FAILED.append(name)
        print(f"  FAIL {name}{(' -- ' + detail) if detail else ''}")


def eq(name: str, got, want) -> None:
    check(name, got == want, f"got {got!r}, want {want!r}")


def ts(dt: datetime, style: str = "plus") -> str:
    if style == "plus":
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")
    return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"


def ago(**kwargs) -> datetime:
    return NOW - timedelta(**kwargs)


# --------------------------------------------------------------------------- #
# load the module under test (the filename has dashes, so importlib it is)
# --------------------------------------------------------------------------- #
def load_audit():
    # A test must not leave a __pycache__ in the repo it is testing.
    sys.dont_write_bytecode = True
    spec = importlib.util.spec_from_file_location("owner_text_audit", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ot = load_audit()


# --------------------------------------------------------------------------- #
# the live schemas, copied verbatim
# --------------------------------------------------------------------------- #
SCHEMA = {
    "sms_log": """
CREATE TABLE sms_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                twilio_sid TEXT,
                direction TEXT NOT NULL DEFAULT 'outbound',
                from_number TEXT NOT NULL,
                to_number TEXT NOT NULL,
                body TEXT NOT NULL,
                template_id TEXT,
                status TEXT NOT NULL DEFAULT 'queued',
                error_message TEXT,
                agent_id TEXT DEFAULT 'orchestrator',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )""",
    "owner_text_turn": """
CREATE TABLE owner_text_turn (
        id           INTEGER PRIMARY KEY AUTOINCREMENT,
        sent_at      TEXT NOT NULL,
        body         TEXT NOT NULL,
        reason       TEXT NOT NULL DEFAULT '',
        urgency      TEXT NOT NULL DEFAULT 'normal',
        sid          TEXT NOT NULL DEFAULT '',
        answered_at  TEXT,
        answer_body  TEXT,
        answered_code TEXT NOT NULL DEFAULT ''
    , handler TEXT NOT NULL DEFAULT '', ref TEXT NOT NULL DEFAULT '')""",
    "owner_decision_queue": """
CREATE TABLE owner_decision_queue (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    asked_at      TEXT NOT NULL,
    question      TEXT NOT NULL,
    context       TEXT,
    options_json  TEXT,
    recommendation TEXT,
    severity      TEXT NOT NULL DEFAULT 'medium',
    blocks        TEXT,
    source        TEXT,
    age_days      INTEGER,
    status        TEXT NOT NULL DEFAULT 'pending',
    answered_at   TEXT,
    answer        TEXT,
    resolved_at   TEXT,
    resolution    TEXT
, deferred_until TEXT, deferred_at TEXT, defer_note TEXT)""",
    "owner_message_queue": """
CREATE TABLE owner_message_queue (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                body TEXT NOT NULL,
                reason TEXT DEFAULT '',
                urgency TEXT DEFAULT 'normal',
                status TEXT NOT NULL DEFAULT 'queued',
                created_at TEXT NOT NULL,
                sent_at TEXT
            , repeat_count INTEGER DEFAULT 1, last_seen_at TEXT, send_attempts INTEGER DEFAULT 0, last_send_error TEXT, status_note TEXT, obligation_key TEXT, next_attempt_at TEXT)""",
    "attempt": """
CREATE TABLE attempt (
    attempt_id     INTEGER PRIMARY KEY AUTOINCREMENT,
    at             TEXT    NOT NULL,
    door           TEXT    NOT NULL,
    subsystem      TEXT    NOT NULL,
    body           TEXT    NOT NULL DEFAULT '',
    body_hash      TEXT    NOT NULL,
    reason         TEXT    NOT NULL DEFAULT '',
    urgency        TEXT    NOT NULL DEFAULT 'normal',
    class_hint     TEXT,
    ref            TEXT,
    topic          TEXT,
    opens_ask      INTEGER NOT NULL DEFAULT 0,
    verdict        TEXT    NOT NULL,
    verdict_reason TEXT    NOT NULL,
    detail         TEXT    NOT NULL DEFAULT '',
    holds          TEXT    NOT NULL DEFAULT '[]',
    status         TEXT    NOT NULL DEFAULT 'pending',
    sid            TEXT    NOT NULL DEFAULT '',
    sent_at        TEXT,
    failed_at      TEXT,
    error          TEXT    NOT NULL DEFAULT '',
    to_number      TEXT    NOT NULL DEFAULT ''
)""",
    "ask": """
CREATE TABLE ask (
    ask_id      INTEGER PRIMARY KEY AUTOINCREMENT,
    ref         TEXT    NOT NULL UNIQUE,
    subsystem   TEXT    NOT NULL,
    topic       TEXT    NOT NULL DEFAULT '',
    body        TEXT    NOT NULL DEFAULT '',
    asked_at    TEXT    NOT NULL,
    ttl_hours   REAL    NOT NULL DEFAULT 72.0,
    expires_at  TEXT    NOT NULL,
    state       TEXT    NOT NULL DEFAULT 'open',
    answered_at TEXT,
    answered_by TEXT,
    answer      TEXT,
    attempt_id  INTEGER
)""",
    "clarification": """
CREATE TABLE clarification (
  id                 INTEGER PRIMARY KEY AUTOINCREMENT,
  reference          TEXT    NOT NULL,
  asker              TEXT    NOT NULL DEFAULT 'cfo-ask',
  channel            TEXT    NOT NULL DEFAULT 'sms',
  cluster_key        TEXT    NOT NULL,
  merchant           TEXT    NOT NULL,
  merchant_name      TEXT,
  description        TEXT,
  entity_id          TEXT,
  account_id         TEXT,
  account_name       TEXT,
  last_four          TEXT,
  transaction_ids    TEXT    NOT NULL DEFAULT '[]',
  txn_count          INTEGER NOT NULL DEFAULT 0,
  max_cents          INTEGER NOT NULL DEFAULT 0,
  total_cents        INTEGER NOT NULL DEFAULT 0,
  question           TEXT    NOT NULL,
  suggest_category   TEXT,
  asked_at           TEXT    NOT NULL,
  outbound_ok        INTEGER NOT NULL DEFAULT 0,
  outbound_sid       TEXT,
  outbound_detail    TEXT,
  state              TEXT    NOT NULL DEFAULT 'asked',
  answer             TEXT,
  answered_at        TEXT,
  answered_via       TEXT,
  open_at_answer     INTEGER,
  rule_id            TEXT,
  rule_created       INTEGER NOT NULL DEFAULT 0,
  rule_detail        TEXT,
  superseded_by      TEXT,
  updated_at         TEXT    NOT NULL
)""",
}


def make_db(path: Path, tables: tuple) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    for name in tables:
        conn.execute(SCHEMA[name])
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# the fixture: exactly the conditions, and nothing else
# --------------------------------------------------------------------------- #
TRUNCATED = "Long text here. [cut short - ask me to continue]"
TRUNCATED_FULL = (TRUNCATED + " And this is the rest of the original that the "
                  "composer dropped on the floor, which is the whole point.")

def build_fixture(root: Path):
    authority = root / "authority.db"
    relay = root / "relay.db"
    cfo = root / "asks.db"

    c = make_db(authority, ("sms_log", "owner_text_turn", "owner_decision_queue",
                            "owner_message_queue"))
    sms = [
        # (sid, direction, to, body, status, created_at)
        # A: one delivery, logged TWICE with the SAME sid -> delivered=1, not a repeat
        ("SM1", "outbound", OWNER, "Hello there", "delivered", ago(days=1)),
        ("SM1", "outbound", OWNER, "Hello there", "delivered",
         ago(days=1) + timedelta(seconds=2)),
        # B: the live DOUBLE SEND shape -- same body, different sids, 0.3 s apart
        ("SM2", "outbound", OWNER, "Same Body Twice", "queued", ago(days=2)),
        ("SM3", "outbound", OWNER, "same   body twice", "queued",
         ago(days=2) + timedelta(seconds=0.3)),
        # C: a body sent three times over three days -> max_repeat = 3
        ("SM4", "outbound", OWNER, "Repeat three", "queued", ago(days=3)),
        ("SM5", "outbound", OWNER, "repeat three", "queued", ago(days=4)),
        ("SM6", "outbound", OWNER, "Repeat THREE", "queued", ago(days=5)),
        # D: suppressed -> refused, and it carries NO sid
        (None, "outbound", OWNER, "Won't go", "suppressed", ago(days=1)),
        # E: failed
        ("SMX", "outbound", OWNER, "Boom", "failed", ago(days=1)),
        # F: inbound
        ("SMIN", "inbound", OWNER, "hi", "received", ago(days=1)),
        # G/H: truncation (G's original is recoverable, H's is not)
        ("SM7", "outbound", OWNER, TRUNCATED, "queued", ago(days=1)),
        ("SM8", "outbound", OWNER, "Trailing off\u2026", "queued", ago(days=1)),
        # I: another recipient -- must not enter any owner metric
        ("SM9", "outbound", FAMILY, "Repeat three", "queued", ago(days=3)),
    ]
    for sid, direction, to, body, status, at in sms:
        from_number = OWNER if direction == "inbound" else "+18480000000"
        c.execute(
            "INSERT INTO sms_log (twilio_sid, direction, from_number, to_number,"
            " body, status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (sid, direction, from_number, to, body, status, ts(at), ts(at)))

    turns = [
        # id, sent, answered
        (ago(hours=72), None),                      # backlog (72h > 48h)
        (ago(hours=24), None),                      # open but not yet backlog
        (ago(hours=2), ago(hours=2) + timedelta(minutes=30)),   # latency 30
        (ago(hours=2), ago(hours=2) + timedelta(minutes=90)),   # latency 90
        (ago(days=10), ago(days=1)),                 # latency 12960, answered after expiry
    ]
    for sent, answered in turns:
        c.execute(
            "INSERT INTO owner_text_turn (sent_at, body, reason, answered_at, sid)"
            " VALUES (?,?,?,?,?)",
            (ts(sent), f"turn at {ts(sent)}", "test", ts(answered) if answered else None, ""))

    c.execute("INSERT INTO owner_message_queue (body, created_at) VALUES (?,?)",
              (TRUNCATED_FULL, ts(ago(days=1))))

    c.execute("INSERT INTO owner_decision_queue (asked_at, question, severity, status)"
              " VALUES (?,?,?,?)",
              (ts(ago(days=3)), "stale decision", "medium", "pending"))
    c.commit()
    c.close()

    r = make_db(relay, ("attempt", "ask"))
    attempts = [
        # (at, door, body, sid, status, verdict, verdict_reason, ref, to_number)
        # THE LIVE SHAPE, CORRECTED. One family message fans out to two members, so these two
        # rows are the SAME body with two sids 0.3 s apart and two DIFFERENT recipients. They
        # are one message to two people and must NOT be counted as a duplicate send -- this is
        # attempts 66/67 and 71/72, which a same-body rule reported as seven defects.
        (ago(days=2), "family_chat", "Dup family", "SMR1", "sent", "SEND", "ok", None,
         "+18483897895"),
        (ago(days=2) + timedelta(seconds=0.3), "family_chat", "dup family", "SMR2",
         "sent", "SEND", "ok", None, "+18482245096"),
        # A GENUINE duplicate: same body, same recipient, two sids, 0.4 s apart. This is what
        # the metric exists to catch, and it must still fire.
        (ago(days=3), "app", "Real double send", "SMR3", "sent", "SEND", "ok", None,
         "+18483897895"),
        (ago(days=3) + timedelta(seconds=0.4), "app", "real double send", "SMR4", "sent",
         "SEND", "ok", None, "+18483897895"),
        # the live silent-outcome shape
        (ago(hours=7), "textsend", "Stuck message body that never left", "", "pending",
         "SEND", "too-long", "owner_message_queue:1", "+18483897895"),
        # a row with a sid is NOT silent: Twilio took it and our ledger never learned the
        # final status. That is a different defect and must not be counted as "unsent".
        (ago(hours=6.5), "textsend", "Sent but never promoted", "SMR9", "queued",
         "SEND", "ok", None, "+18483897895"),
        # still inside the 6h grace window
        (ago(hours=1), "textsend", "Fresh pending", "", "pending", "SEND", "ok", None,
         "+18483897895"),
        # carries the truncated body AND the ref that recovers its original
        (ago(days=1), "textsend", TRUNCATED, "SMR5", "sent", "SEND", "ok",
         "owner_message_queue:1", "+18483897895"),
    ]
    for at, door, body, sid, status, verdict, reason, ref, to in attempts:
        r.execute(
            "INSERT INTO attempt (at, door, subsystem, body, body_hash, verdict,"
            " verdict_reason, status, sid, ref, to_number) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (ts(at, "z"), door, door, body, f"h{len(body)}", verdict, reason, status,
             sid, ref, to))

    asks = [
        # (ref, body, asked, answered, answered_by)
        ("ask-1792163692", "CFO [ask-1792163692]: what was 114.04 at Adjust membership fee",
         ago(days=2), ago(days=2) + timedelta(minutes=25), "owner"),
        # answered at the very same instant -> the ">0 minutes" boundary
        ("ask-1792000000", "CFO [ask-1792000000]: 31.73 at Visiontek",
         ago(days=3), ago(days=3), "owner"),
        # a self-test row is not a production defect
        ("selftest-20261015T1525", "CFO [selftest-20261015T1525]: what was 12.00 at X",
         ago(days=4), ago(days=4) + timedelta(seconds=0.12), "owner"),
        # no currency amount at all
        ("attempt-29", "36 items, 18 urgent", ago(days=5), None, None),
        # answered by something that is not the owner
        ("ask-1791777777", "CFO [ask-1791777777]: 42.50 at Somewhere",
         ago(days=6), ago(days=6), "cfo-bot"),
    ]
    for ref, body, asked, answered, by in asks:
        r.execute(
            "INSERT INTO ask (ref, subsystem, body, asked_at, expires_at, state,"
            " answered_at, answered_by, answer) VALUES (?,?,?,?,?,?,?,?,?)",
            (ref, "cfo_ask", body, ts(asked, "z"), ts(asked + timedelta(hours=72), "z"),
             "answered" if answered else "open",
             ts(answered, "z") if answered else None, by,
             "yes" if answered else None))

    clarifications = [
        # the SAME question as ask-1792163692, answered by a reference -> counted once
        ("ask-1792163692", "CFO [ask-1792163692]: what was 114.04 at Adjust",
         ago(days=2), ago(days=2) + timedelta(minutes=18), "reference"),
        # a question the CFO closed itself
        ("ask-1791999999", "CFO [ask-1791999999]: 55.00 at Office Depot",
         ago(days=3), ago(days=3) + timedelta(minutes=40), "reference"),
        # the owner answered this one -- not an internal ask
        ("ask-1791888888", "CFO [ask-1791888888]: 10.00 at X",
         ago(days=4), ago(days=4) + timedelta(minutes=7), "owner"),
    ]
    r.commit()
    r.close()

    q = make_db(cfo, ("clarification",))
    for ref, question, asked, answered, via in clarifications:
        q.execute(
            "INSERT INTO clarification (reference, cluster_key, merchant, question,"
            " asked_at, answered_at, answered_via, answer, updated_at)"
            " VALUES (?,?,?,?,?,?,?,?,?)",
            (ref, ref, "merchant", question, ts(asked), ts(answered), via, "yes",
             ts(answered)))
    q.commit()
    q.close()

    return authority, relay, cfo


def build_clean_fixture(root: Path):
    """Nothing to find: one delivered text, one answered turn, nothing stuck."""
    authority = root / "clean-authority.db"
    relay = root / "clean-relay.db"
    cfo = root / "clean-asks.db"

    c = make_db(authority, ("sms_log", "owner_text_turn", "owner_decision_queue",
                            "owner_message_queue"))
    c.execute(
        "INSERT INTO sms_log (twilio_sid, direction, from_number, to_number, body,"
        " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("SMCLEAN", "outbound", "+18480000000", OWNER, "one text, once", "delivered",
         ts(ago(hours=2)), ts(ago(hours=2))))
    c.execute(
        "INSERT INTO sms_log (twilio_sid, direction, from_number, to_number, body,"
        " status, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
        ("SMCLEANIN", "inbound", OWNER, "+18480000000", "ok", "received",
         ts(ago(hours=1)), ts(ago(hours=1))))
    c.execute(
        "INSERT INTO owner_text_turn (sent_at, body, reason, answered_at, sid)"
        " VALUES (?,?,?,?,?)",
        (ts(ago(hours=2)), "one question", "test",
         ts(ago(hours=2) + timedelta(minutes=12)), "SMCLEAN"))
    c.commit()
    c.close()

    r = make_db(relay, ("attempt", "ask"))
    r.execute(
        "INSERT INTO attempt (at, door, subsystem, body, body_hash, verdict,"
        " verdict_reason, status, sid) VALUES (?,?,?,?,?,?,?,?,?)",
        (ts(ago(hours=2), "z"), "textsend", "textsend", "one text, once", "hc",
         "SEND", "ok", "sent", "SMCLEAN"))
    r.commit()
    r.close()

    make_db(cfo, ("clarification",)).close()
    return authority, relay, cfo


def env_for(authority: Path, relay: Path, cfo: Path) -> dict:
    env = dict(os.environ)
    env["OWNER_TEXT_AUDIT_AUTHORITY_DB"] = str(authority)
    env["OWNER_TEXT_AUDIT_RELAY_DB"] = str(relay)
    env["OWNER_TEXT_AUDIT_CFO_DB"] = str(cfo)
    env["PYTHONIOENCODING"] = "utf-8"
    # make sure a stray wake CLI in the environment cannot be called by a test
    env["WAKE_PY"] = str(authority.parent / "no-such-wake.py")
    return env


def apply_env(env: dict) -> None:
    """Point the in-process module at the fixture, not at the authority."""
    for key in ("OWNER_TEXT_AUDIT_AUTHORITY_DB", "OWNER_TEXT_AUDIT_RELAY_DB",
                "OWNER_TEXT_AUDIT_CFO_DB", "WAKE_PY"):
        os.environ[key] = env[key]


def run_cli(args, env):
    return subprocess.run(
        [sys.executable, str(SCRIPT)] + args,
        capture_output=True, text=True, encoding="utf-8", env=env, timeout=120)


# --------------------------------------------------------------------------- #
def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        authority, relay, cfo = build_fixture(root)
        env = env_for(authority, relay, cfo)
        apply_env(env)

        # ---------------- metric by metric, through the real code ------------- #
        print("metric 1: delivery")
        audit = ot.Audit(since=ot.now_utc() - timedelta(days=14),
                         until=ot.now_utc(), days=14)
        results = ot.collect(audit)
        audit.close()

        delivery = results["delivery"]
        eq("delivery computed", delivery["reason"], None)
        v = delivery["value"]
        eq("delivered counts DISTINCT sids (duplicate log collapsed)", v["delivered"], 1)
        eq("duplicate log rows were read, not ignored",
           delivery["raw"]["delivered_rows_not_deduped"], 2)
        eq("duplicate log collapse is reported",
           delivery["raw"]["duplicate_log_rows_collapsed"], 1)
        eq("refused counts suppressed rows", v["refused"], 1)
        eq("failed counts failed rows", v["failed"], 1)
        eq("inbound counts inbound rows", v["inbound"], 1)
        eq("refusal_rate = refused/(delivered+refused+failed)",
           round(v["refusal_rate"], 4), round(1 / 3, 4))
        eq("another recipient is not in the owner's delivery count",
           delivery["raw"]["outbound_rows_to_owner"], 11)

        print("metric 2: repeat_index")
        repeat = results["repeat_index"]
        eq("repeat_index computed", repeat["reason"], None)
        eq("max_repeat is the most-repeated body", repeat["value"]["max_repeat"], 3)
        eq("a body carried by ONE sid twice is not a repeat",
           [e["body"] for e in repeat["value"]["repeat_index"]].count("hello there"), 0)
        eq("the most repeated body is listed first (as first sent)",
           repeat["value"]["repeat_index"][0]["body"], "Repeat THREE")
        eq("repeated bodies found", len(repeat["value"]["repeat_index"]), 2)

        print("metric 3: double_sends")
        doubles = results["double_sends"]
        eq("double_sends computed", doubles["reason"], None)
        eq("owner half catches the 0.3s same-body pair",
           doubles["value"]["owner_sms_log"], 1)
        # CORRECTED 2026-10-18. The fixture used to assert that the relay's family_chat pair
        # (same body, two sids, 0.2 s apart) was a duplicate. It is not: it is one message to
        # the owner and one to a family member, and the ledger could not tell them apart
        # because it had no recipient column -- so a same-body rule reported seven correct
        # sends as defects. A pair now counts only when both rows name the SAME recipient.
        eq("a pair to two different recipients is NOT a duplicate",
           doubles["raw"]["relay_pairs"], 1)
        check("the pair found is the genuine same-recipient one",
              any({p["a"]["sid"], p["b"]["sid"]} == {"SMR3", "SMR4"}
                  for p in doubles["value"]["pairs"]))
        eq("total is owner + relay", doubles["value"]["total"], 2)
        eq("worst pair is the 0.3s one",
           doubles["value"]["worst"]["delta_seconds"], 0.3)
        eq("worst pair reports distinct sids",
           doubles["value"]["worst"]["a"]["sid"] != doubles["value"]["worst"]["b"]["sid"],
           True)

        print("metric 4: silent_outcomes")
        silent = results["silent_outcomes"]
        eq("silent_outcomes computed", silent["reason"], None)
        eq("only the >6h pending row counts", silent["value"]["count"], 1)
        eq("oldest three carry door + body prefix",
           silent["value"]["oldest"][0]["door"], "textsend")
        eq("the live too-long shape is the one found",
           silent["value"]["oldest"][0]["verdict_reason"], "too-long")
        check("body prefix is 60 chars or fewer",
              len(silent["value"]["oldest"][0]["body"]) <= 60)

        print("metric 5: unanswered_backlog")
        backlog = results["unanswered_backlog"]
        eq("unanswered_backlog computed", backlog["reason"], None)
        eq("only the >48h unanswered turn is backlog", backlog["value"]["count"], 1)
        eq("answered_after_expiry finds the >7d answer",
           backlog["value"]["answered_after_expiry"], 1)

        print("metric 6: answer_latency")
        latency = results["answer_latency"]
        eq("answer_latency computed", latency["reason"], None)
        eq("three answered turns are in the window",
           latency["value"]["answered_turns"], 3)
        eq("median of 30, 90, 12960 is 90",
           latency["value"]["median_minutes"], 90.0)
        eq("the exact SQL is on record",
           "julianday(answered_at)" in latency["raw"]["sql"], True)

        print("metric 7: internal_asks")
        internal = results["internal_asks"]
        eq("internal_asks computed", internal["reason"], None)
        eq("same question in both stores is counted once",
           internal["value"]["count"], 2)
        eq("answered_by values are reported raw",
           internal["raw"]["answered_by_values"].get("owner"), 3)
        eq("an answer that is not the owner is counted separately",
           internal["raw"]["answered_by_not_owner_or_number"], 1)
        eq("a zero-minute answer is not an internal ask",
           internal["raw"]["rows_answered_at_zero_minutes"], 2)
        eq("a selftest row is excluded",
           internal["raw"]["excluded_selftest_rows"], 1)
        eq("worst internal ask is the 40-minute one",
           internal["value"]["worst"][0]["minutes"], 40.0)

        print("metric 8: truncation")
        trunc = results["truncation"]
        eq("truncation computed", trunc["reason"], None)
        eq("both truncation markers are found", trunc["value"]["count"], 2)
        eq("the original is recovered through attempt.ref",
           trunc["value"]["originals_recoverable"], 1)
        check("dropped characters are positive",
              trunc["value"]["dropped_chars"] > 0,
              f"dropped={trunc['value']['dropped_chars']}")
        eq("the unrecoverable one is reported as such",
           trunc["raw"]["originals_unrecoverable"], 1)

        print("supporting: owner_decision_queue")
        decision = results["decision_queue"]
        eq("decision_queue computed", decision["reason"], None)
        eq("stale pending decisions count", decision["value"]["pending_over_48h"], 1)

        # ---------------- thresholds and the flag ---------------------------- #
        print("thresholds")
        eq("THRESHOLDS is exactly the six specified",
           {k: v for k, v in ot.THRESHOLDS.items()},
           {"double_sends": 0, "silent_outcomes": 0, "unanswered_backlog": 0,
            "max_repeat": 1, "internal_asks": 2, "refusal_rate": 0.5})
        values = ot.flat_values(results)
        fired = ot.breaches(values)
        fired_names = sorted(b["metric"] for b in fired)
        eq("internal_asks=2 does NOT breach '>2'", "internal_asks" in fired_names, False)
        eq("the four real breaches are found", fired_names,
           ["double_sends", "max_repeat", "silent_outcomes", "unanswered_backlog"])

        healthy = {"double_sends": 0, "silent_outcomes": 0, "unanswered_backlog": 0,
                   "max_repeat": 1, "internal_asks": 2, "refusal_rate": 0.5}
        eq("nothing breaches on healthy values", ot.breaches(healthy), [])
        eq("an unmeasured (null) metric cannot breach",
           ot.breaches(dict(healthy, double_sends=None)), [])

        defects = ot.rank_defects(results, values)
        eq("three defects are ranked", len(defects), 3)
        eq("a text he sees twice outranks a stuck row",
           defects[0]["metric"], "double_sends")
        eq("defect evidence names the ids and the gap",
           "0.3s apart" in defects[0]["evidence"], True)

        print("the flag prompt")
        now = ot.now_utc()
        audit = ot.Audit(since=now - timedelta(days=14), until=now, days=14)
        prompt = ot.build_prompt(audit, values, fired, defects, results)
        audit.close()
        check("prompt is under 2500 characters", len(prompt) < 2500, f"{len(prompt)}")
        check("prompt carries the metric table", "METRIC" in prompt and "VALUE" in prompt)
        check("prompt carries the breached thresholds",
              "double_sends = 2 > 0" in prompt, prompt[:400])
        check("prompt carries the standing instruction",
              "Find the single worst defect" in prompt
              and "prove the fix against the live ledger" in prompt)
        check("prompt names the subject week", ot.iso_week(now) in prompt)
        check("subject is stable per ISO week",
              ot.iso_week(now) == ot.iso_week(now - timedelta(days=1))
              or now.weekday() == 0)

        # ---------------- the CLI contract ---------------------------------- #
        print("CLI: --json")
        proc = run_cli(["--json", "--days", "14"], env)
        eq("exit 0 when every metric computes", proc.returncode, 0)
        payload = json.loads(proc.stdout)
        eq("json has every metric", set(payload["metrics"]), {
            "delivery", "repeat_index", "double_sends", "silent_outcomes",
            "unanswered_backlog", "answer_latency", "internal_asks", "truncation",
            "decision_queue"})
        eq("json delivered value survives the round trip",
           payload["values"]["delivered"], 1)
        eq("json reports no unmeasured metric", payload["unmeasured"], {})
        check("json carries the raw query text",
              "julianday(answered_at)" in payload["metrics"]["answer_latency"]["raw"]["sql"])

        print("CLI: human report")
        proc = run_cli(["--days", "14"], env)
        eq("human report exits 0 with defects present", proc.returncode, 0)
        check("human report prints the raw number beside the predicate",
              "double_sends" in proc.stdout and "2" in proc.stdout)
        check("human report states the duplicate-log rule",
              "DISTINCT twilio_sid" in proc.stdout)
        check("human report ranks the defects",
              "DEFECTS, WORST FIRST" in proc.stdout and "[double_sends]" in proc.stdout)

        print("CLI: --flag --dry-run")
        proc = run_cli(["--flag", "--dry-run", "--days", "14"], env)
        eq("dry-run exits 0", proc.returncode, 0)
        check("dry-run writes nothing and says so",
              "nothing written" in proc.stdout)
        check("dry-run prints the exact brief",
              "STANDING INSTRUCTION" in proc.stdout)
        check("dry-run uses the stable subject",
              f"owner-text-audit:{ot.iso_week(ot.now_utc())}" in proc.stdout)

        print("CLI: usage errors")
        eq("--days 0 is a usage error", run_cli(["--days", "0"], env).returncode, 3)
        eq("--json with --flag is a usage error",
           run_cli(["--json", "--flag"], env).returncode, 3)
        eq("a bad --since is a usage error",
           run_cli(["--since", "18-10-2026"], env).returncode, 3)

        print("CLI: one unreadable source")
        empty = root / "empty.db"
        sqlite3.connect(empty).close()
        broken = env_for(authority, relay, empty)
        proc = run_cli(["--json", "--days", "14"], broken)
        eq("exit 2 when one source is unreadable", proc.returncode, 2)
        payload = json.loads(proc.stdout)
        eq("the broken metric is null",
           payload["metrics"]["internal_asks"]["value"], None)
        check("the broken metric carries a reason",
              "clarification" in (payload["metrics"]["internal_asks"]["reason"] or ""))
        eq("the other metrics still report",
           payload["values"]["delivered"], 1)
        eq("the unmeasured metric is named", "internal_asks" in payload["unmeasured"], True)

        print("CLI: a missing database entirely")
        missing = env_for(authority, relay, root / "nope" / "asks.db")
        proc = run_cli(["--json", "--days", "14"], missing)
        eq("exit 2 when a database file is absent", proc.returncode, 2)
        check("the reason names the path",
              "no database at" in proc.stderr or "no database at" in proc.stdout)

        print("CLI: --since")
        proc = run_cli(["--json", "--since",
                        (ot.now_utc() - timedelta(days=7)).strftime("%Y-%m-%d")], env)
        eq("--since wins over --days and still exits 0", proc.returncode, 0)
        payload = json.loads(proc.stdout)
        eq("--since is recorded as the window choice",
           payload["window"]["chosen_by"], "--since")

        print("CLI: a clean channel files NOTHING")
        c_authority, c_relay, c_cfo = build_clean_fixture(root)
        clean = env_for(c_authority, c_relay, c_cfo)
        proc = run_cli(["--flag", "--days", "14"], clean)
        eq("a clean run exits 0", proc.returncode, 0)
        check("a clean run says no flag in the exact words",
              "no flag: all metrics within threshold" in proc.stdout,
              proc.stdout[-300:])
        check("a clean run never prints a brief",
              "STANDING INSTRUCTION" not in proc.stdout)
        check("a clean run does not claim a dry-run filed anything",
              "would file" not in proc.stdout)
        proc = run_cli(["--json", "--days", "14"], clean)
        payload = json.loads(proc.stdout)
        eq("a clean run has no breaches", payload["breaches"], [])
        eq("a clean run measures zero double sends",
           payload["values"]["double_sends"], 0)
        eq("a clean run measures one delivery", payload["values"]["delivered"], 1)
        eq("a clean run measures no repeat", payload["values"]["max_repeat"], 0)
        eq("a clean run measures no internal asks",
           payload["values"]["internal_asks"], 0)
        eq("a clean run measures no truncation",
           payload["values"]["truncation"], 0)

    print("")
    if FAILED:
        print(f"{PASSED} passed, {len(FAILED)} FAILED")
        for name in FAILED:
            print(f"  FAILED: {name}")
        return 1
    print(f"{PASSED} passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
