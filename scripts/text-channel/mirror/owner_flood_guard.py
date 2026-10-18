#!/usr/bin/env python3
"""owner_flood_guard: the brake on an identical owner-bound message, and the one number
that makes a flood visible from the channel.

MEASURED 2026-10-01 against the authority, read-only:

    select count(*) from sms_log
     where to_number like '%8483897895%' and direction='outbound'
       and created_at >= '2026-10-01' and created_at < '2026-10-02';
    -> 925 rows, 911 of them status='suppressed', 0 of them holding a twilio_sid
    (927 = the same query with NO upper bound: the two rows written after midnight)

Two bodies are 908 of those rows, and every row carries the same refusal:

    '... Reminder: Check 300DDR for Fishman tickets 74114 ...'  618 rows, 09-30T16:58Z -> 10-01T14:02Z
    '... Reminder: CALL TOPGOLF EDISON GUEST CARE ...'          290 rows, 10-01T15:04Z -> 10-01T21:58Z
    error_message: '[suppressed] owner_text gate refused (too_long):
                    is 811 chars, over the 320-char limit for one text'

WHO WRITES THAT, HONESTLY. The writer is the app's own owner-message flush
(`app/autopilot.py::_flush_owner_message_queue`, reached once per autopilot tick, ~60 s)
and the refusal is `app/owner_text.gate()`. Neither file is in this directory, so this
module CANNOT stop that loop and does not claim to. What it owns is:

  * the brake on THIS channel's owner-bound sends -- `textsend.send()` and
    `textsend.notify_owner()` call `decide()` before and `note()` after every attempt;
  * the single definition of "an attempt", so the instrument
    (`text-health.py`) can count the app's suppressed rows too (`app_attempt_groups`
    reads `sms_log`, every status, because a `suppressed` row is an attempt nobody
    looks at -- which is why E1 read OK on 2026-10-01 while 911 rows were written).

THE THREE RULES, from journal pain P2819 and the owner-queue row #235:

  1. AN OWNER-BOUND BODY IS NEVER REFUSED FOR LENGTH. A body that does not fit is a
     formatting problem, never a reason for silence, so the caller fits it (see
     `textsend.fit_owner_body`) and this module records what actually went.
  2. A RE-FIRE BACKS OFF EXPONENTIALLY PER (RECIPIENT, BODY-HASH): the n-th identical
     attempt inside one hour may not start until `BACKOFF_BASE_SECONDS * 2 ** (n-1)`
     has passed, capped at `BACKOFF_MAX_SECONDS`. The measured flood re-fired every
     ~60 s because nothing counted attempts at all.
  3. MORE THAN `BREAKER_ATTEMPTS_PER_HOUR` IDENTICAL ATTEMPTS IN ONE HOUR TRIPS THE
     BREAKER: further attempts are refused before any network call, and exactly ONE
     owner-queue row is raised -- so a stuck retry becomes the one question that can
     clear it instead of a counter that nobody reads.

WHY N = 5. Three measurements and none of them is taste:
  * every retry policy this codebase already has is smaller -- `textstore.job_sweep`
    gives up after 3, a wake row gets 2 -- so 3 attempts already covers a real
    transient (a Twilio 5xx, a lock, a dropped socket). 5 is 1.7x the loosest of them.
  * the measured flood rate is ~60/hour (one per tick). 5 is 12x below it: a healthy
    channel cannot reach it, a broken one cannot miss it.
  * with rule 2 in force, the backoff itself can produce at most 5 attempts in an hour
    (gaps 60, 120, 240, 480 s => t = 0, 60, 180, 420, 900 s). The breaker therefore
    fires only once the backoff has already stretched retries to eight minutes apart
    and is demonstrably not working -- it cannot pre-empt its own brake.

IT IS ONE NUMBER, IN ONE PLACE. `BREAKER_ATTEMPTS_PER_HOUR` and `ATTEMPT_WINDOW_MINUTES`
are the constants; `text-health.py` imports them rather than repeating them, and its C2
check fails when this module is absent from the deployed tree.

CLI
    python3 owner_flood_guard.py status [--hours 24] [--json]
    python3 owner_flood_guard.py check --to +18483897895 --body "..." | --body-file F
    python3 owner_flood_guard.py attempts --hours 24 [--json]

Read-only for `status`/`check`/`attempts`. `note()` writes the attempt ledger, and
`trip()` raises at most one owner-queue row. Nothing here sends a text to anyone.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
HERE = Path(__file__).resolve().parent
BIN = HOME / "bin"

# ── THE ONE NUMBER ─────────────────────────────────────────────────────────────
#: Identical attempts to one recipient inside :data:`ATTEMPT_WINDOW_MINUTES` before the
#: breaker trips and the retrying stops. The arithmetic for 5 is in the module header.
BREAKER_ATTEMPTS_PER_HOUR = 5
#: The window the breaker counts in -- one hour, the unit the owner's complaints and the
#: flood were both measured in.
ATTEMPT_WINDOW_MINUTES = 60
#: Rule 2: the first re-fire may not start for this long, and each further one doubles.
BACKOFF_BASE_SECONDS = 60
BACKOFF_MAX_SECONDS = 900

#: The one thing that proves a row in `owner_decision_queue` is this module's, so a
#: hundred trips leave one question and not a hundred.
MARKER = "[owner-flood-guard]"

DEFAULT_DB = HOME / ".sms-inbox" / "inbox.db"
DEFAULT_APP_DB = HOME / "personal-secretary-mvp" / "data" / "secretary.db"
QUEUE_CLI = HOME / "bin" / "owner-queue.py"

#: The app's own one-text ceiling (`app/owner_text.DEFAULT_MAX_CHARS`), and the env name
#: it is overridden by. Named here so a caller can fit a body to the SAME limit the gate
#: that will judge it uses, instead of guessing.
APP_OWNER_TEXT_MAX_CHARS = 320
ENV_OWNER_TEXT_MAX_CHARS = "OWNER_TEXT_MAX_CHARS"

SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS send_attempt (
        id         INTEGER PRIMARY KEY AUTOINCREMENT,
        recipient  TEXT NOT NULL,
        body_hash  TEXT NOT NULL,
        body_head  TEXT NOT NULL DEFAULT '',
        outcome    TEXT NOT NULL,
        code       TEXT NOT NULL DEFAULT '',
        detail     TEXT NOT NULL DEFAULT '',
        at         TEXT NOT NULL
    );
    """,
    "CREATE INDEX IF NOT EXISTS idx_send_attempt_key ON send_attempt(recipient, body_hash, at);",
    """
    CREATE TABLE IF NOT EXISTS flood_breaker (
        recipient    TEXT NOT NULL,
        body_hash    TEXT NOT NULL,
        tripped_at   TEXT NOT NULL,
        attempts     INTEGER NOT NULL DEFAULT 0,
        question_ref TEXT NOT NULL DEFAULT '',
        PRIMARY KEY (recipient, body_hash)
    );
    """,
)

#: Outcomes that mean "we really tried": the message was handed to a transport (or to the
#: app) and came back delivered, refused, suppressed or failed. A pre-flight refusal by
#: THIS module is deliberately not in here: the brake counting its own refusals would let
#: a caller trip the breaker just by asking, which is the feedback loop the brake exists
#: to end.
ATTEMPT_OUTCOMES = ("sent", "delivered", "failed", "suppressed", "refused", "held")


# --------------------------------------------------------------------------- #
# Time, identity, bodies
# --------------------------------------------------------------------------- #
def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(moment: datetime | None = None) -> str:
    return (moment or utcnow()).astimezone(timezone.utc).isoformat(timespec="seconds")


def parse_stamp(value) -> datetime | None:
    """A tolerant parse of BOTH stamp formats this system writes: ISO-8601 (with a 'T')
    and the app's own. Returns an aware datetime or None, never raises.

    The 'T' matters. Measured 2026-10-02: `created_at >= datetime('now','-1 hour')`
    selects 927 rows, because SQLite's datetime() writes '2026-10-01 23:56:00' and every
    ISO stamp sorts ABOVE it at the 'T' (0x54 > 0x20) -- so a comparison that looks like
    "the last hour" returns nine days of history. Never compare these as strings.
    """
    text = str(value or "").strip()
    if not text:
        return None
    try:
        moment = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                moment = datetime.strptime(text, fmt)
                break
            except ValueError:
                moment = None
        if moment is None:
            return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


def digits(phone) -> str:
    return re.sub(r"\D", "", str(phone or ""))


def tail(phone) -> str:
    """The last ten digits: how every query in this system compares a phone."""
    return digits(phone)[-10:]


def normalise(body) -> str:
    """The canonical form of a body, so two spellings of one message are one key.

    Lower-cased, punctuation and whitespace flattened, first 160 characters -- the SAME
    rule `text-health.py` used before this module existed, kept here so the instrument and
    the brake cannot disagree about whether two rows are the same message.
    """
    text = re.sub(r"[^a-z0-9 ]", " ", str(body or "").lower())
    return " ".join(text.split())[:160]


def body_hash(body) -> str:
    """A stable short hash of :func:`normalise`d text. The identity of a message."""
    return hashlib.sha1(normalise(body).encode("utf-8")).hexdigest()[:16]


def body_head(body, limit: int = 70) -> str:
    return " ".join(str(body or "").split())[:limit]


def _cell(row, name: str, index: int):
    """One column from a row, whichever `row_factory` the CALLER's connection uses.

    THIS IS A LIBRARY RULE, and it was measured as a defect on 2026-10-02: the guard's
    own connections set `sqlite3.Row`, but `text-health.py` hands it its own read-only
    connection, whose rows are plain tuples. Indexing by name raised

        TypeError: tuple indices must be integers or slices, not str

    inside E1 and E2, so the instrument printed FAIL for a bug in the instrument rather
    than for the flood -- and the failure it reported was a Python error, which is exactly
    the shape of "an instrument that is not running", the class of defect this whole
    exercise is about. Two rules follow, and both are kept here: a function that takes a
    caller's connection may not assume its row type, and it may not let a type error reach
    the caller as if it were a reading.
    """
    try:
        return row[name]
    except (TypeError, IndexError, KeyError):
        return row[index]


def owner_text_ceiling(cfg: dict | None = None) -> int:
    """The app's one-text ceiling, resolved the way the app resolves it."""
    raw = (cfg or {}).get("owner_text_max_chars") or os.environ.get(ENV_OWNER_TEXT_MAX_CHARS)
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        return APP_OWNER_TEXT_MAX_CHARS
    return max(0, value)


# --------------------------------------------------------------------------- #
# Where the two ledgers are
# --------------------------------------------------------------------------- #
def _as_path(raw: str) -> Path:
    if raw.startswith("sqlite:///"):
        return Path(raw[len("sqlite:///"):])
    if raw.startswith("sqlite://"):
        return Path(raw[len("sqlite://"):])
    if raw.startswith("file:"):
        return Path(raw[len("file:"):].split("?")[0])
    return Path(raw)


def store_path(cfg: dict | None = None) -> Path:
    raw = (cfg or {}).get("db") or os.environ.get("SMS_INBOX_DB")
    return _as_path(raw) if raw else DEFAULT_DB


def app_db_path(cfg: dict | None = None) -> Path:
    """The app's database, resolved the way `textsend.app_db_path` resolves it.

    Deliberately NOT from the merged `.env`'s `DATABASE_URL` (which always names
    production, so an environment override could never win). `textsend` passes its own
    resolved path in, so in the send path there is still exactly one answer.
    """
    cfg = cfg or {}
    for key in ("app_db", "app_db_path"):
        raw = str(cfg.get(key) or "").strip()
        if raw:
            return _as_path(raw)
    for key in ("SECRETARY_DB", "SECRETARY_DATABASE_URL", "DATABASE_URL", "SMS_APP_DB"):
        raw = str(os.environ.get(key) or "").strip()
        if raw:
            return _as_path(raw)
    return DEFAULT_APP_DB


def connect(path=None, *, create_dir: bool = True) -> sqlite3.Connection:
    p = Path(path) if path else store_path()
    if create_dir:
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=20)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=20000")
    except sqlite3.Error:
        pass
    return conn


def ro_connect(path) -> sqlite3.Connection | None:
    """Read-only, or None. An unreadable ledger is reported as unreadable, never as 'no
    attempts': the whole defect this module exists for was a check that read the wrong
    store and called the channel healthy."""
    try:
        if not Path(path).exists():
            return None
        return sqlite3.connect(f"file:{path}?mode=ro", uri=True, timeout=10)
    except sqlite3.Error:
        return None


#: What this module's tables are for, so `doctor`-style output can name them.
TABLES = ("send_attempt", "flood_breaker")

#: An attempt that did NOT reach the owner, by the outcome or the app's status. Anything
#: else is an attempt that did. One list, used by the instrument and the CLI, because
#: "911 suppressed and 0 delivered" and "911 delivered" are different worlds and a bare
#: total cannot tell them apart.
REFUSED_OUTCOMES = ("suppressed", "failed", "undelivered", "refused", "held", "error")


def ensure_schema(conn: sqlite3.Connection) -> dict:
    """Create the attempt ledger and the breaker table. Additive only, never DROP.

    Also called on a pre-existing store by `textstore.ensure_schema` (v3 migration), so
    the schema has one definition and the store module keeps ownership of the shape.
    """
    for statement in SCHEMA_SQL:
        try:
            conn.execute(statement)
        except sqlite3.Error:
            pass
    conn.commit()
    return {"ok": True, "tables": TABLES}


# --------------------------------------------------------------------------- #
# The attempt ledger
# --------------------------------------------------------------------------- #
def record_attempt(conn: sqlite3.Connection, recipient: str, body, outcome: str,
                   *, code: str = "", detail: str = "", at: datetime | None = None) -> int:
    """Write one attempt. `outcome` is what happened; a pre-flight refusal by this
    module is not an attempt and is never written here (see `ATTEMPT_OUTCOMES`)."""
    ensure_schema(conn)
    cur = conn.execute(
        "INSERT INTO send_attempt (recipient, body_hash, body_head, outcome, code, detail, at) "
        "VALUES (?,?,?,?,?,?,?)",
        (str(recipient or ""), body_hash(body), body_head(body), str(outcome or "")[:32],
         str(code or "")[:64], str(detail or "")[:400], _stamp(at)))
    conn.commit()
    return int(cur.lastrowid or 0)


def channel_attempt_times(conn: sqlite3.Connection, recipient: str, bhash: str,
                          since: datetime) -> list[datetime]:
    """Every attempt THIS channel made, from its own ledger."""
    if conn is None:
        return []
    try:
        rows = conn.execute(
            "SELECT at, outcome FROM send_attempt WHERE recipient=? AND body_hash=? AND at >= ?",
            (str(recipient or ""), bhash, _stamp(since))).fetchall()
    except sqlite3.Error:
        return []
    return [m for m in (parse_stamp(_cell(r, "at", 0)) for r in rows) if m is not None]


def app_attempt_times(app_conn: sqlite3.Connection, recipient: str, bhash: str,
                      since: datetime) -> list[datetime]:
    """Every attempt the APP made to this recipient with this body, from `sms_log`.

    EVERY status counts -- queued, sent, delivered, failed, suppressed, undelivered. That
    is the whole point: on 2026-10-01 the channel's own store held none of these rows and
    the ones that did reach it were all `delivered`, so a duplicate check that counted
    only delivered rows printed OK while 911 rows were being written.
    """
    return [m for m, row_hash, _ in app_attempt_rows(app_conn, recipient, since)
            if m is not None and row_hash == bhash]


def app_attempt_rows(app_conn: sqlite3.Connection, recipient: str,
                     since: datetime) -> list[tuple]:
    """`(moment, body_hash, status)` for every outbound attempt to this recipient.

    One read, normalised in Python (`normalise` is a regex, not a SQL function), so the
    instrument can group by body without a second definition of "same message".
    """
    if app_conn is None:
        return []
    tail_digits = tail(recipient)
    if not tail_digits:
        return []
    try:
        rows = app_conn.execute(
            "SELECT created_at, body, status FROM sms_log "
            "WHERE direction='outbound' AND to_number LIKE ?",
            ("%" + tail_digits + "%",)).fetchall()
    except sqlite3.Error:
        return []
    out = []
    for created_at, body, status in rows:
        moment = parse_stamp(created_at)
        if moment is None or moment < since:
            continue
        out.append((moment, body_hash(body), str(status or "")))
    return out


def attempts_between(times: list[datetime], now: datetime, window: timedelta) -> list[datetime]:
    return sorted(t for t in times if t is not None and now - window <= t <= now)


# --------------------------------------------------------------------------- #
# The decision
# --------------------------------------------------------------------------- #
class Decision(dict):
    """The brake's verdict. A dict so a caller can print it, with attribute sugar."""

    @property
    def allowed(self) -> bool:
        return bool(self.get("allowed"))

    @property
    def code(self) -> str:
        return str(self.get("code") or "")

    @property
    def wait_seconds(self) -> float:
        return float(self.get("wait_seconds") or 0.0)

    def __getattr__(self, name):                      # pragma: no cover - sugar only
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def decide(recipient: str, body, *, now: datetime | None = None,
           conn: sqlite3.Connection | None = None,
           app_conn: sqlite3.Connection | None = None,
           include_app: bool = True) -> Decision:
    """May this exact message go to this exact recipient right now?

    Read-only. Three answers:

      ``allowed``  nothing identical has been attempted often enough to matter, or the
                   last one was long enough ago.
      ``backoff``  an identical attempt is too recent; ``wait_seconds`` says how long.
      ``breaker``  :data:`BREAKER_ATTEMPTS_PER_HOUR` identical attempts inside
                   :data:`ATTEMPT_WINDOW_MINUTES`; stop retrying and raise ONE question.

    The count is the channel's own ledger UNION the app's `sms_log`, because an attempt
    made by the other half of this system is still an attempt on the owner's phone.
    """
    moment = now or utcnow()
    bhash = body_hash(body)
    window = timedelta(minutes=ATTEMPT_WINDOW_MINUTES)
    since_hour = moment - window

    times = list(channel_attempt_times(conn, recipient, bhash, since_hour))
    if include_app:
        times += app_attempt_times(app_conn, recipient, bhash, since_hour)
    recent = attempts_between(times, moment, window)

    out = {"recipient": str(recipient or ""), "body_hash": bhash, "allowed": True,
           "code": "ok", "wait_seconds": 0.0, "attempts_last_hour": len(recent),
           "window_minutes": ATTEMPT_WINDOW_MINUTES,
           "threshold": BREAKER_ATTEMPTS_PER_HOUR, "detail": ""}

    if len(recent) >= BREAKER_ATTEMPTS_PER_HOUR:
        out["allowed"] = False
        out["code"] = "breaker"
        out["detail"] = (
            "%d identical attempt(s) in the last %d min (threshold %d) - retrying stops "
            "here; one owner-queue row is raised instead"
            % (len(recent), ATTEMPT_WINDOW_MINUTES, BREAKER_ATTEMPTS_PER_HOUR))
        return Decision(out)

    if recent:
        # Rule 2: exponential per (recipient, body-hash). `n` is how many have already
        # been attempted in this series, so gaps are base, 2x, 4x, 8x ... capped.
        last = recent[-1]
        need = min(BACKOFF_BASE_SECONDS * (2 ** (len(recent) - 1)), BACKOFF_MAX_SECONDS)
        waited = (moment - last).total_seconds()
        if waited < need:
            out["allowed"] = False
            out["code"] = "backoff"
            out["wait_seconds"] = round(need - waited, 1)
            out["detail"] = (
                "identical attempt %d in the last %d min was %.0fs ago; the backoff for "
                "attempt %d is %.0fs (base %ds, doubling, capped at %ds)"
                % (len(recent), ATTEMPT_WINDOW_MINUTES, waited, len(recent) + 1, need,
                   BACKOFF_BASE_SECONDS, BACKOFF_MAX_SECONDS))
        else:
            out["detail"] = ("%d identical attempt(s) in the last %d min, last one %.0fs "
                             "ago - past the %.0fs backoff, allowed"
                             % (len(recent), ATTEMPT_WINDOW_MINUTES, waited, need))
        return Decision(out)

    out["detail"] = ("no identical attempt in the last %d min - first send of this body "
                     "to this recipient" % ATTEMPT_WINDOW_MINUTES)
    return Decision(out)


# --------------------------------------------------------------------------- #
# The breaker: exactly one question, ever
# --------------------------------------------------------------------------- #
def breaker_row(conn: sqlite3.Connection, recipient: str, bhash: str) -> dict | None:
    """The breaker row for (recipient, body), or None.

    Rebuilt by column name so it works on a caller's plain-tuple connection as well as on
    this module's own `sqlite3.Row` ones: `dict(row)` on a tuple raises a TypeError that
    the `sqlite3.Error` guard around it would not catch, and a brake that raises is a
    brake that does nothing.
    """
    if conn is None:
        return None
    cols = ("recipient", "body_hash", "tripped_at", "attempts", "question_ref")
    try:
        row = conn.execute(
            "SELECT recipient, body_hash, tripped_at, attempts, question_ref FROM flood_breaker "
            "WHERE recipient=? AND body_hash=?", (str(recipient or ""), bhash)).fetchone()
    except sqlite3.Error:
        return None
    if not row:
        return None
    try:
        return {c: row[c] for c in cols}
    except (TypeError, IndexError, KeyError):
        return dict(zip(cols, tuple(row)))


def _pending_question_id(app_conn: sqlite3.Connection, bhash: str) -> int:
    """Is this module's question for this body already open? Read-only, and the answer is
    0 (not an exception) when the queue cannot be read -- a queue we cannot read must not
    become a queue we write to twice."""
    if app_conn is None:
        return 0
    try:
        rows = app_conn.execute(
            "SELECT id, question FROM owner_decision_queue WHERE status='pending'").fetchall()
    except sqlite3.Error:
        return 0
    for rid, question in rows:
        if MARKER in str(question or "") and bhash in str(question or ""):
            return int(rid)
    return 0


def raise_question(question: str, *, context: str = "", severity: str = "high",
                   source: str = "owner-flood-guard", timeout: int = 60) -> int:
    """Raise one owner-queue row through the documented CLI. Returns its id, or 0.

    `owner-queue.py add` refuses a byte-identical question (exit 4) and this module's own
    `flood_breaker` row refuses a second attempt before we get here, so the "exactly one"
    in rule 3 has two independent enforcements.
    """
    if not Path(QUEUE_CLI).exists():
        return 0
    cmd = ["python3", str(QUEUE_CLI), "add", "--question", question,
           "--recommendation", "Stop retrying and let me tell you once, when you reply.",
           "--options", "Tell me once when I reply|Drop it", "--severity", severity,
           "--source", source]
    if context:
        cmd += ["--context", context]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except Exception:
        return 0
    blob = (proc.stdout or "") + "\n" + (proc.stderr or "")
    for match in re.findall(r"#(\d+)", blob):
        return int(match)
    return 0


def trip(recipient: str, body, *, attempts: int, conn: sqlite3.Connection | None = None,
         app_conn: sqlite3.Connection | None = None, queue_add=None,
         now: datetime | None = None, context: str = "") -> dict:
    """Trip the breaker for (recipient, body). Raises AT MOST ONE owner-queue row.

    Idempotent three ways: this module's own `flood_breaker` row, a pending
    `owner_decision_queue` row carrying the marker and the body hash, and
    `owner-queue.py`'s own byte-identical duplicate guard.
    """
    moment = now or utcnow()
    bhash = body_hash(body)
    existing = breaker_row(conn, recipient, bhash)
    if existing:
        return {"tripped": False, "already": True, "queue_id": existing.get("question_ref") or 0,
                "attempts": existing.get("attempts") or attempts,
                "detail": "the breaker already tripped for this body at %s"
                          % existing.get("tripped_at")}
    pending = _pending_question_id(app_conn, bhash)
    if pending:
        _remember(conn, recipient, bhash, attempts, str(pending), moment)
        return {"tripped": False, "already": True, "queue_id": pending, "attempts": attempts,
                "detail": "owner-queue row #%d already asks this" % pending}

    question = (
        "I have tried %d times in the last hour to send you the same text and every attempt "
        "was refused - do you want it once, when you reply to something, or should I drop it? "
        "%s %s" % (attempts, MARKER, bhash))
    detail = ("%d identical attempt(s) inside %d min for %s (%s). Body: %s"
              % (attempts, ATTEMPT_WINDOW_MINUTES, recipient, bhash, body_head(body)))
    if context:
        detail = context + " | " + detail
    queue_id = 0
    if queue_add is not None:
        queue_id = int(queue_add(question, detail) or 0)
    else:
        queue_id = raise_question(question, context=detail)
    _remember(conn, recipient, bhash, attempts, str(queue_id or ""), moment)
    return {"tripped": True, "already": False, "queue_id": queue_id, "attempts": attempts,
            "detail": "breaker tripped: %d identical attempts; question #%s"
                      % (attempts, queue_id or "(not raised)")}


def _remember(conn, recipient, bhash, attempts, question_ref, moment) -> None:
    if conn is None:
        return
    try:
        ensure_schema(conn)
        conn.execute(
            "INSERT OR REPLACE INTO flood_breaker "
            "(recipient, body_hash, tripped_at, attempts, question_ref) VALUES (?,?,?,?,?)",
            (str(recipient or ""), bhash, _stamp(moment), int(attempts), str(question_ref or "")))
        conn.commit()
    except sqlite3.Error:
        pass


# --------------------------------------------------------------------------- #
# note(): record an attempt and, at the threshold, trip exactly once
# --------------------------------------------------------------------------- #
def note(recipient: str, body, outcome: str, *, code: str = "", detail: str = "",
         conn: sqlite3.Connection | None = None, app_conn: sqlite3.Connection | None = None,
         queue_add=None, now: datetime | None = None) -> dict:
    """Record one attempt, then trip the breaker if it was the one that crossed the line.

    This is what makes "five identical suppressed sends leave exactly ONE queue row"
    true: the row is raised by the fifth `note()`, and the sixth `decide()` is refused.
    """
    moment = now or utcnow()
    outcome = str(outcome or "").strip().lower()
    if outcome in ATTEMPT_OUTCOMES and conn is not None:
        record_attempt(conn, recipient, body, outcome, code=code, detail=detail, at=moment)
    window = timedelta(minutes=ATTEMPT_WINDOW_MINUTES)
    times = list(channel_attempt_times(conn, recipient, body_hash(body), moment - window))
    times += app_attempt_times(app_conn, recipient, body_hash(body), moment - window)
    count = len(attempts_between(times, moment, window))
    out = {"attempts_last_hour": count, "threshold": BREAKER_ATTEMPTS_PER_HOUR,
           "tripped": False, "queue_id": 0, "allowed_next": True, "detail": ""}
    if count >= BREAKER_ATTEMPTS_PER_HOUR:
        trip_result = trip(recipient, body, attempts=count, conn=conn, app_conn=app_conn,
                           queue_add=queue_add, now=moment)
        out.update({"tripped": True, "queue_id": trip_result.get("queue_id") or 0,
                    "already_tripped": trip_result.get("already"), "allowed_next": False,
                    "detail": trip_result.get("detail") or ""})
    return out


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #
def _window(hours: float, now: datetime | None = None) -> datetime:
    return (now or utcnow()) - timedelta(hours=float(hours))


def attempts_report(hours: float = 24.0, *, conn=None, app_conn=None,
                    now: datetime | None = None) -> list[dict]:
    """Every (recipient, body) with an attempt in the window, worst first.

    Counts BOTH ledgers, and carries the split, because "911 suppressed and 0 delivered"
    and "911 delivered" are different worlds that a single total cannot tell apart.
    """
    moment = now or utcnow()
    since = _window(hours, moment)
    groups: dict[tuple, dict] = {}

    def _bump(recipient, bhash, head, when, source, status):
        key = (str(recipient or ""), bhash)
        row = groups.setdefault(key, {"recipient": recipient, "body_hash": bhash,
                                      "body_head": head, "attempts": 0, "channel": 0,
                                      "app": 0, "refused": 0, "delivered": 0,
                                      "statuses": {}, "first": None, "last": None})
        row["attempts"] += 1
        row[source] = row.get(source, 0) + 1
        if str(status or "").lower() in REFUSED_OUTCOMES:
            row["refused"] += 1
        else:
            row["delivered"] += 1
        row["statuses"][status] = row["statuses"].get(status, 0) + 1
        row["first"] = when if row["first"] is None or when < row["first"] else row["first"]
        row["last"] = when if row["last"] is None or when > row["last"] else row["last"]

    if conn is not None:
        try:
            for r in conn.execute(
                    "SELECT recipient, body_hash, body_head, outcome, at FROM send_attempt "
                    "WHERE at >= ?", (_stamp(since),)).fetchall():
                when = parse_stamp(_cell(r, "at", 4))
                if when:
                    _bump(_cell(r, "recipient", 0), _cell(r, "body_hash", 1),
                          _cell(r, "body_head", 2), when, "channel",
                          str(_cell(r, "outcome", 3) or ""))
        except sqlite3.Error:
            pass
    if app_conn is not None:
        try:
            rows = app_conn.execute(
                "SELECT to_number, created_at, body, status FROM sms_log "
                "WHERE direction='outbound'").fetchall()
        except sqlite3.Error:
            rows = []
        for to_number, created_at, body, status in rows:
            when = parse_stamp(created_at)
            if when is None or when < since:
                continue
            _bump(to_number, body_hash(body), body_head(body), when, "app", str(status or ""))

    out = []
    for row in groups.values():
        for key in ("first", "last"):
            row[key] = _stamp(row[key]) if row[key] else ""
        out.append(row)
    out.sort(key=lambda r: (-r["attempts"], r["last"]))
    return out


def cmd_status(args) -> int:
    now = utcnow()
    st = ro_connect(store_path())          # read-only: an instrument must not migrate
    ap = ro_connect(app_db_path())
    rows = attempts_report(args.hours, conn=st, app_conn=ap, now=now)
    hot = [r for r in rows if r["attempts"] >= BREAKER_ATTEMPTS_PER_HOUR]
    print("OWNER-FLOOD-GUARD %s" % _stamp(now))
    print("threshold  %d identical attempts / %d min (backoff %ds doubling, cap %ds)"
          % (BREAKER_ATTEMPTS_PER_HOUR, ATTEMPT_WINDOW_MINUTES, BACKOFF_BASE_SECONDS,
             BACKOFF_MAX_SECONDS))
    print("ledgers    channel=%s app=%s" % (store_path(), app_db_path()))
    print("%d (recipient, body) group(s) with an attempt in the last %.0f h; %d at or "
          "above the threshold" % (len(rows), float(args.hours), len(hot)))
    for r in rows[:args.limit]:
        flag = "BREAKER " if r["attempts"] >= BREAKER_ATTEMPTS_PER_HOUR else "        "
        print("  %s%d attempts  channel=%d app=%d refused=%d delivered=%d  %s..%s  %s"
              % (flag, r["attempts"], r["channel"], r["app"], r["refused"], r["delivered"],
                 r["first"], r["last"], r["body_head"]))
    if args.json:
        print(json.dumps(rows[:args.limit], indent=2, default=str))
    return 1 if hot else 0


def cmd_check(args) -> int:
    body = Path(args.body_file).read_text(encoding="utf-8").strip() if args.body_file else (args.body or "")
    st = ro_connect(store_path())
    ap = ro_connect(app_db_path())
    d = decide(args.to, body, conn=st, app_conn=ap)
    print("recipient  %s" % d["recipient"])
    print("body_hash  %s  (%s)" % (d["body_hash"], body_head(body)))
    print("verdict    %s" % ("ALLOWED" if d.allowed else "REFUSED (%s)" % d.code))
    print("detail     %s" % d["detail"])
    return 0 if d.allowed else 1


def cmd_attempts(args) -> int:
    rows = attempts_report(args.hours, conn=ro_connect(store_path()),
                           app_conn=ro_connect(app_db_path()))
    if args.json:
        print(json.dumps(rows, indent=2, default=str))
        return 0
    print("%d group(s) in the last %.0f h" % (len(rows), float(args.hours)))
    for r in rows[:args.limit]:
        print("  %4d  channel=%d app=%d  %s" % (r["attempts"], r["channel"], r["app"],
                                                r["body_head"]))
    return 0


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("status")
    s.add_argument("--hours", type=float, default=24.0)
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    c = sub.add_parser("check")
    c.add_argument("--to", required=True)
    c.add_argument("--body", default="")
    c.add_argument("--body-file", default="")
    c.set_defaults(func=cmd_check)

    a = sub.add_parser("attempts")
    a.add_argument("--hours", type=float, default=24.0)
    a.add_argument("--limit", type=int, default=40)
    a.add_argument("--json", action="store_true")
    a.set_defaults(func=cmd_attempts)

    args = p.parse_args(argv)
    if not getattr(args, "func", None):
        args = p.parse_args(["status"])
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
