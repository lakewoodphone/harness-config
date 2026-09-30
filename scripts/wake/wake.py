#!/usr/bin/env python3
"""The wake queue and its safety envelope.

THE PROBLEM THIS SOLVES. The secretary can SEE things - every inbound text is
reconciled from Twilio every five minutes - but nothing on a Linux server can
START a DSH session, so anything that needs real work sits until a human opens
one. `dsh --profile headless "<task>"` answers one task and exits (verified
2026-09-18), so the missing piece is a queue: anything that knows there is work
raises a **flag**, and a dispatcher turns a flag into a session.

THE RULE THAT KEEPS THIS FROM BECOMING A SESSION FACTORY:
    A wake row is only ever filed by something that knows there IS work.
    Nothing on a timer may file work. A dispatcher releases; it never invents.

Every guard in the contract's section 4 exists to make that rule hold under
failure, not to make it optional.

THREE LAYERS, and this file is only the third:
    1. CAPTURE  sms-inbox.py   - reconcile inbound/outbound texts from Twilio.
    2. ROUTE    sms-responder.py - answer, or file one owner-decision row.
    3. FLAG     this file        - the queue the dispatcher releases from.

USAGE
    wake.py flag --subject S --prompt P [--kind K] [--source SRC]
                 [--priority high|normal|low] [--context C]
                 [--cooldown-seconds N] [--max-attempts N] [--json]
    wake.py claim --by NAME [--lease-seconds N] [--json]
    wake.py heartbeat ID --by NAME [--lease-seconds N]
    wake.py finish ID --outcome TEXT [--cost-usd X]   |  finish ID --failed ...
    wake.py reap [--json]
    wake.py list [--state S] [--limit N] [--json]
    wake.py stats [--json]
    wake.py pause | resume
    wake.py await PHONE --what W [--name N] [--until DATE] [--created-by X]
    wake.py awaits [--all]
    wake.py add ...            (alias of flag; kept for the responder)

EXIT CODES.  `flag` exits 0 no matter what - a flag that can break its caller is
worse than no flag; it prints exactly one of
`filed` / `deduped` / `suppressed:<reason>` / `capped`. Every other verb exits 0
on success and 2 on a usage or database error it could not handle.

A BROKEN STORE MUST NOT LOOK LIKE A QUIET ONE. `flag` exits 0 even when the
store itself is broken, so the result string has to carry the difference:
`filed`/`deduped`/`suppressed:<known reason>`/`capped` are decisions, and an
unexpected exception prints `error:<ExceptionClass>: <message>` on stdout with
the traceback on stderr (`{"ok": false, ...}` with `--json`). It is NEVER
reported as `suppressed:*` - a silent suppression is a system that looks green
while the queue stays empty and the dispatcher idles, which is the exact failure
this design exists to prevent.

A WOKEN SESSION MUST NOT RAISE FLAGS. A headless session runs this same CLI, so
a session that misunderstands its task could file a flag, which releases another
session, which files another - unbounded recursion. Therefore: if `WAKE_SESSION`
is set to a non-empty value, **the store layer refuses to file anything** and
returns `suppressed:inside-a-woken-session`, whatever the caller is. The
dispatcher sets it in the environment of every session it launches. An explicit
`--allow-from-session` on `flag`/`add` overrides it for the rare deliberate
case. This lives in `file_wake()` rather than in the CLI so that every caller -
`flag`, `add`, `_file_wake` in sms-responder.py - inherits it.

ENVIRONMENT (all read AT CALL TIME, never at import, so tests can set them):
    SMS_INBOX_DB, SMS_INBOX_APP_DB, SMS_INBOX_ENV   - the store (sms-inbox.py)
    WAKE_COOLDOWN_SEC           (1800) guard 2
    WAKE_MAX_PER_DAY          (500)    guard 3  (NOT the limiting guard - see
                                        DEFAULT_MAX_PER_DAY: the real limit is the
                                        70 USD/day spend cap, below)
    WAKE_MAX_PER_SOURCE_PER_HOUR(12)   guard 4 - raised 2026-09-30: one number, every reader
    WAKE_NIGHT_QUIET            (1)    guard 5
    WAKE_PAUSE_FILE             (~/.sms-inbox/WAKE_PAUSED) guard 6
    WAKE_LEASE_SEC              (1200) guard 7
    WAKE_MAX_ATTEMPTS           (2)    guard 9
    WAKE_MAX_USD_PER_DAY        (70.0)  guard 10
    WAKE_SESSION                - set inside a woken session; refuses every flag
                                  (guard 11, always on)
    WAKE_CLOCK_ISO      - test/ops override for "now" (ISO8601). A time gate
                          that cannot be exercised by a test is not a guard.
    WAKE_SMS_INBOX_PY   - path to sms-inbox.py if it is not found next to this
                          file or one directory up.

INTERPRETATIONS the contract left open (implemented, and reported as such):
    * `capped`  - the row IS filed (state `new`, id returned); the word reports
      that a cap is currently in force so it will not be released yet. Guard 3
      says explicitly that over the cap "the row stays new".
    * Re-filing a subject whose row is terminal (`done`/`failed`/`cancelled`/
      `expired`) revives it, because the UNIQUE subject means a second row is
      impossible and "one live row per issue" is the intent. Reviving a row
      that has already failed `max_attempts` times prints
      `suppressed:attempts` - guard 9 outranks guard 1.
    * The per-source cap counts wake rows with a claim in the last rolling hour,
      by source, so a noisy source cannot starve the rest of the queue.
"""
from __future__ import annotations

import argparse
import contextlib
import json
import os
import sqlite3
import sys
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

# --------------------------------------------------------------------------- #
# sms-inbox.py - the store connection, the same one every other layer uses.
# --------------------------------------------------------------------------- #
def _find_sms_inbox() -> Path | None:
    here = Path(__file__).resolve().parent
    cands = [
        here / "sms-inbox.py",
        here.parent / "sms-inbox.py",
        here.parent.parent / "sms-inbox.py",
    ]
    override = os.environ.get("WAKE_SMS_INBOX_PY")
    if override:
        cands.insert(0, Path(override).expanduser())
    cands.append(Path.home() / "bin" / "sms-inbox.py")
    for c in cands:
        try:
            if c.is_file():
                return c
        except OSError:
            continue
    return None


class _FallbackInbox:
    """Used only if sms-inbox.py cannot be loaded. Keeps `flag` exiting 0."""

    def __init__(self) -> None:
        import re

        self._re = re
        home = Path.home()
        self.ENV_FILE = Path(os.environ.get("SMS_INBOX_ENV",
                                            home / "personal-secretary-mvp" / ".env"))
        self.APP_DB = Path(os.environ.get("SMS_INBOX_APP_DB",
                                          home / "personal-secretary-mvp" / "data" / "secretary.db"))
        self.STORE = Path(os.environ.get("SMS_INBOX_DB", home / ".sms-inbox" / "inbox.db"))

    def connect(self) -> sqlite3.Connection:
        self.STORE.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(self.STORE), timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA busy_timeout=30000")
        return conn

    def norm(self, p: str) -> str:
        d = self._re.sub(r"\D", "", p or "")
        return d[-10:] if len(d) >= 10 else d


def _load_inbox():
    path = _find_sms_inbox()
    if path is None:
        print("wake: sms-inbox.py not found - using the built-in store fallback",
              file=sys.stderr)
        return _FallbackInbox()
    import importlib.util

    spec = importlib.util.spec_from_file_location("sms_inbox", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


inbox = _load_inbox()

SCHEMA = """
CREATE TABLE IF NOT EXISTS wake (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    subject      TEXT NOT NULL UNIQUE,        -- dedup key; one live row per issue
    kind         TEXT NOT NULL DEFAULT 'task',
    source       TEXT NOT NULL DEFAULT 'manual',
    prompt       TEXT NOT NULL,
    context      TEXT NOT NULL DEFAULT '',
    priority     TEXT NOT NULL DEFAULT 'normal',   -- high|normal|low
    created_at   TEXT NOT NULL,
    not_before   TEXT,                             -- cooldown gate, ISO8601
    state        TEXT NOT NULL DEFAULT 'new',      -- new|claimed|done|failed|cancelled|expired
    attempts     INTEGER NOT NULL DEFAULT 0,
    max_attempts INTEGER NOT NULL DEFAULT 2,
    claimed_by   TEXT, claimed_at TEXT, lease_until TEXT,
    finished_at  TEXT, outcome TEXT, cost_usd REAL
);

CREATE TABLE IF NOT EXISTS wake_budget (
    day      TEXT PRIMARY KEY,      -- UTC YYYY-MM-DD
    released INTEGER NOT NULL DEFAULT 0,
    failed   INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS awaited (phone TEXT PRIMARY KEY, name TEXT, what TEXT NOT NULL,
    sent_at TEXT NOT NULL, until TEXT, created_by TEXT DEFAULT 'zabz',
    state TEXT NOT NULL DEFAULT 'active');
"""

# Indexes are a SEPARATE script on purpose. `CREATE INDEX ... ON wake(source)`
# against an existing v0 table fails with "no such column: source" and takes the
# whole connect() with it, so the indexes are created only after the migration.
SCHEMA_INDEXES = """
CREATE INDEX IF NOT EXISTS idx_wake_state ON wake(state);
CREATE INDEX IF NOT EXISTS idx_wake_source ON wake(source);
"""

# Columns added after v0 was deployed. `CREATE TABLE IF NOT EXISTS` will not add
# a column to a table that already exists, and the live table on the authority
# is v0 - so the migration is part of the schema, not an afterthought.
_WAKE_ADDED_COLUMNS = {
    "kind": "TEXT NOT NULL DEFAULT 'task'",
    "source": "TEXT NOT NULL DEFAULT 'manual'",
    "context": "TEXT NOT NULL DEFAULT ''",
    "priority": "TEXT NOT NULL DEFAULT 'normal'",
    "not_before": "TEXT",
    "attempts": "INTEGER NOT NULL DEFAULT 0",
    "max_attempts": "INTEGER NOT NULL DEFAULT 2",
    "claimed_by": "TEXT",
    "claimed_at": "TEXT",
    "lease_until": "TEXT",
    "finished_at": "TEXT",
    "outcome": "TEXT",
    "cost_usd": "REAL",
}

# The columns section 3 requires. Kept as a list so `stats`-style introspection
# and the tests can assert completeness rather than trust the DDL above.
WAKE_COLUMNS = (
    "id", "subject", "kind", "source", "prompt", "context", "priority",
    "created_at", "not_before", "state", "attempts", "max_attempts",
    "claimed_by", "claimed_at", "lease_until", "finished_at", "outcome", "cost_usd",
)

STATES = ("new", "claimed", "done", "failed", "cancelled", "expired")
LIVE_STATES = ("new", "claimed")
TERMINAL_STATES = ("done", "failed", "cancelled", "expired")

MAX_NOT_BEFORE_REASONS = {
    "paused": "the kill switch is on",
    "daily-cap": "the daily release cap is reached",
    "cost-cap": "the daily spend cap is reached",
    "night-quiet": "low-priority releases are outside their window",
    "source-cap": "this source is at its hourly release cap",
    "attempts": "this subject has failed its maximum attempts",
    "cooldown": "this subject was released recently",
    "usage": "the caller did not supply a subject and a prompt",
    "error": "an internal error was caught so the caller survives",
}


# --------------------------------------------------------------------------- #
# time, environment and the store - everything read AT CALL TIME
# --------------------------------------------------------------------------- #
def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


DEFAULT_MAX_PER_DAY = 500

# THE ACTUAL LIMIT: the owner's 70 USD/day of DeepSeek API spend.
# He set the ceiling himself on 2026-09-28: "obviously we can't have overall more than $70 of
# spending, let's say, on the deepseek API daily. But it's not like how many times."
# At the MEASURED 0.068 USD per autonomous shift (38 priced releases, 2.5825 USD total in
# ~/.sms-inbox/wake-cost.jsonl) that is roughly 1,029 shifts/day, so this binds only when
# something is pathological - which is precisely what it is for. Volume is not the limit;
# waste is.
DEFAULT_MAX_USD_PER_DAY = 70.0

def _env_int(name: str, default: int) -> int:
    try:
        return int(str(_env_str(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _env_float(name: str, default: float) -> float:
    try:
        return float(str(_env_str(name, str(default))).strip())
    except (TypeError, ValueError):
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw == "":
        return default
    return str(raw).strip().lower() not in ("0", "false", "no", "off")


def now_dt() -> datetime:
    """UTC now, or the test/ops override. Never cached: a guard that cannot be
    exercised by a test is not a guard."""
    raw = os.environ.get("WAKE_CLOCK_ISO")
    if raw:
        try:
            d = datetime.fromisoformat(raw.strip().replace("Z", "+00:00"))
            return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
        except ValueError:
            pass
    return datetime.now(timezone.utc)


def now() -> str:
    return now_dt().isoformat(timespec="seconds")


def parse_dt(raw) -> datetime | None:
    """Lenient ISO8601 -> aware UTC. Mixed formats in the table are tolerated
    rather than compared as strings."""
    if not raw:
        return None
    txt = str(raw).strip()
    try:
        d = datetime.fromisoformat(txt.replace("Z", "+00:00"))
    except ValueError:
        try:
            d = datetime.strptime(txt[:10], "%Y-%m-%d")
        except ValueError:
            return None
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def today_utc() -> str:
    return now_dt().strftime("%Y-%m-%d")


def pause_file() -> Path:
    raw = os.environ.get("WAKE_PAUSE_FILE")
    if raw:
        return Path(raw).expanduser()
    # The store directory, so an overridden store is overridden all the way.
    return Path(getattr(inbox, "STORE", Path.home() / ".sms-inbox" / "inbox.db")).parent / "WAKE_PAUSED"


def paused() -> bool:
    try:
        return pause_file().exists()
    except OSError:
        return False


def connect() -> sqlite3.Connection:
    conn = inbox.connect()
    conn.isolation_level = None          # explicit transactions only
    _ensure(conn)
    return conn


def _ensure(conn: sqlite3.Connection) -> None:
    """Idempotent: the store has the wake tables and every section-3 column.

    Runs on every connect AND on any connection another component hands us
    (sms-responder.py hands us its own). The authoritative store already has a
    v0 `wake` table, where `CREATE TABLE IF NOT EXISTS` is a no-op, so this is
    the difference between working on the machine that matters and crashing
    with `no such column` there.
    """
    try:
        conn.execute(
            "SELECT id, source, not_before, attempts, max_attempts, lease_until, "
            "cost_usd FROM wake LIMIT 1").fetchone()
        return
    except sqlite3.Error:
        pass
    conn.executescript(SCHEMA)
    _migrate(conn)
    conn.executescript(SCHEMA_INDEXES)


def _migrate(conn: sqlite3.Connection) -> None:
    """Add every column the contract requires that this table does not have.
    Nothing is dropped, rewritten or renamed; existing rows keep their values
    and pick up the column defaults."""
    have = {r["name"] for r in conn.execute("PRAGMA table_info(wake)").fetchall()}
    for col, ddl in _WAKE_ADDED_COLUMNS.items():
        if col not in have:
            conn.execute(f"ALTER TABLE wake ADD COLUMN {col} {ddl}")
    conn.execute("UPDATE wake SET source='manual' WHERE source IS NULL OR source=''")


@contextlib.contextmanager
def _tx(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE: the claim must be atomic against a second dispatcher."""
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield conn
    except BaseException:
        try:
            conn.execute("ROLLBACK")
        except sqlite3.Error:
            pass
        raise
    else:
        conn.execute("COMMIT")


def _rows(conn: sqlite3.Connection, sql: str, params: tuple = ()) -> list[dict]:
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row_dict(row) -> dict | None:
    return dict(row) if row is not None else None


# --------------------------------------------------------------------------- #
# effective caps and the counters behind them
# --------------------------------------------------------------------------- #
def caps_now() -> dict:
    return {
        "max_per_day": _env_int("WAKE_MAX_PER_DAY", DEFAULT_MAX_PER_DAY),
        "max_per_source_per_hour": _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12),
        "max_usd_per_day": _env_float("WAKE_MAX_USD_PER_DAY", DEFAULT_MAX_USD_PER_DAY),
        "cooldown_sec": _env_int("WAKE_COOLDOWN_SEC", 1800),
        "lease_sec": _env_int("WAKE_LEASE_SEC", 1200),
        "max_attempts": _env_int("WAKE_MAX_ATTEMPTS", 2),
        "night_quiet": _env_bool("WAKE_NIGHT_QUIET", True),
        "pause_file": str(pause_file()),
        "paused": paused(),
        "in_session": in_session(),
    }


def released_today(conn: sqlite3.Connection) -> int:
    """RELEASES TODAY - sessions STARTED, not pieces of work.

    `wake_budget.released` is incremented once per release, and a single wake row can be
    released many times in one day: `file_wake` revives a terminal row in place because
    `subject` is UNIQUE, and each source re-files after its own cooldown. Measured
    2026-09-29: 133 releases across 41 distinct wake ids; the subject
    `project:lpt-website:20260929` went out 20 times, all exit=0. For work DONE read the
    ledger (work.py), never this number.
    """
    r = conn.execute("SELECT released FROM wake_budget WHERE day=?", (today_utc(),)).fetchone()
    return int(r["released"]) if r else 0


def failed_today(conn: sqlite3.Connection) -> int:
    r = conn.execute("SELECT failed FROM wake_budget WHERE day=?", (today_utc(),)).fetchone()
    return int(r["failed"]) if r else 0


def spend_today(conn: sqlite3.Connection) -> float | None:
    """The day's autonomous spend in USD, MEASURED, or None when it cannot be measured.

    Reads `~/.sms-inbox/wake-cost.jsonl`, which `wake-cost.py` writes per release and which is
    the only place a real per-shift cost exists: `wake.cost_usd` is null on every row because
    `dsh --profile headless` reports no cost, so the store-based sum this replaced could only
    ever return 0.0 (measured 2026-09-28).

    RELEASED SESSIONS ONLY. The owner's own interactive sessions are not an autonomous cost and
    must not consume the autonomous budget.

    Returns None - never 0.0 - when the measurement is unreadable. An unreadable measurement is
    not a measurement of zero, and reporting it as zero is exactly how a money guard lies.
    """
    path = Path(os.path.expanduser(os.environ.get("WAKE_COST_JSONL")
                                   or "~/.sms-inbox/wake-cost.jsonl"))
    day = today_utc()
    try:
        if not path.exists():
            return None
        total = 0.0
        seen = 0
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line or '"type": "release"' not in line.replace("'", '"'):
                    continue
                try:
                    row = json.loads(line)
                except Exception:
                    continue
                if row.get("type") != "release":
                    continue
                if str(row.get("started_day") or "")[:10] != day:
                    continue
                v = row.get("cost_usd_or_unsourced")
                if isinstance(v, (int, float)):
                    total += float(v)
                    seen += 1
                elif isinstance(v, str) and v not in ("unsourced", ""):
                    try:
                        total += float(v)
                        seen += 1
                    except ValueError:
                        pass
        if seen == 0:
            # No priced release yet today is a real (zero) reading for the autonomous budget.
            return 0.0
        return round(total, 6)
    except Exception:
        return None


# With no measurement, unlimited volume is the runaway the ceiling exists to stop. Below this
# many releases a day the operator's "unmeasured" is acceptable; above it, refuse.
UNMEASURED_REFUSE_ABOVE = 40


def source_releases_last_hour(conn: sqlite3.Connection, source: str) -> int:
    cutoff = now_dt() - timedelta(hours=1)
    n = 0
    for r in conn.execute(
        "SELECT claimed_at FROM wake WHERE source=? AND claimed_at IS NOT NULL", (source,)
    ).fetchall():
        when = parse_dt(r["claimed_at"])
        if when is not None and when >= cutoff:
            n += 1
    return n


def night_quiet_active(when: datetime | None = None) -> bool:
    """Guard 5: `low` releases only between 13:00 and 03:00 UTC."""
    if not _env_bool("WAKE_NIGHT_QUIET", True):
        return False
    hour = (when or now_dt()).hour
    return 3 <= hour < 13


def release_block(conn: sqlite3.Connection) -> str | None:
    """The whole-queue guards checked before anything may be released."""
    if paused():
        return "paused"
    if released_today(conn) >= _env_int("WAKE_MAX_PER_DAY", DEFAULT_MAX_PER_DAY):
        return "daily-cap"
    spent = spend_today(conn)
    if spent is None:
        # NO MEASUREMENT IS NOT ZERO. Refuse only once volume means the risk is real, so an
        # unreadable cost file cannot silently stop the operation either.
        if released_today(conn) > UNMEASURED_REFUSE_ABOVE:
            return "spend-unmeasured"
    elif spent >= _env_float("WAKE_MAX_USD_PER_DAY", DEFAULT_MAX_USD_PER_DAY):
        return "cost-cap"
    return None


def in_session() -> bool:
    """True when this process is running inside a woken session - see the
    module docstring. Read at call time, never cached."""
    return bool(_env_str("WAKE_SESSION", ""))


def caps_in_force(conn: sqlite3.Connection) -> list[str]:
    """Which caps are in force RIGHT NOW, with their values."""
    cap = caps_now()
    out: list[str] = []
    rel = released_today(conn)
    spend = spend_today(conn)
    if cap["paused"]:
        out.append(f"paused: {cap['pause_file']} exists")
    if cap["in_session"]:
        out.append("session_recursion: WAKE_SESSION is set - every flag is refused")
    if rel >= cap["max_per_day"]:
        out.append(f"daily_cap: {rel}/{cap['max_per_day']} releases today")
    if spend >= cap["max_usd_per_day"]:
        out.append(f"cost_cap: ${spend:.4f}/${cap['max_usd_per_day']:.2f} spent today")
    if cap["night_quiet"] and night_quiet_active():
        out.append(
            "night_quiet: low-priority releases blocked until 13:00 UTC "
            f"(now {now_dt().strftime('%H:%M')} UTC)"
        )
    for src, n in sorted(source_releases(conn).items()):
        if n >= cap["max_per_source_per_hour"]:
            out.append(
                f"source_cap: {src} {n}/{cap['max_per_source_per_hour']} in the last hour"
            )
    return out


def source_releases(conn: sqlite3.Connection) -> dict:
    out: dict[str, int] = {}
    for r in conn.execute(
        "SELECT DISTINCT source FROM wake WHERE claimed_at IS NOT NULL"
    ).fetchall():
        src = r["source"] or "manual"
        n = source_releases_last_hour(conn, src)
        if n:
            out[src] = n
    return out


def _bump_budget(conn: sqlite3.Connection, released: int = 0, failed: int = 0) -> None:
    conn.execute(
        """INSERT INTO wake_budget(day, released, failed) VALUES(?,?,?)
           ON CONFLICT(day) DO UPDATE SET released=released+?, failed=failed+?""",
        (today_utc(), released, failed, released, failed),
    )


# --------------------------------------------------------------------------- #
# flag / add - guard 1, 2, 3+10 (reported), 6
# --------------------------------------------------------------------------- #
def _last_release(row: dict) -> datetime | None:
    stamps = [parse_dt(row.get("claimed_at")), parse_dt(row.get("finished_at"))]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def file_wake(conn: sqlite3.Connection, *, subject: str, prompt: str, context: str = "",
              kind: str = "task", source: str = "", priority: str = "normal",
              cooldown_seconds: int | None = None,
              max_attempts: int | None = None,
              allow_from_session: bool = False) -> tuple[str, int | None]:
    """File, dedupe, suppress or cap. Returns (result, row_id). Never raises on
    a guard decision: every decision is one of the four frozen words."""
    # Guard 11, first and unconditional: a woken session must never raise a flag,
    # or one session becomes two becomes a fleet. This is in the store layer on
    # purpose so every caller inherits it.
    if in_session() and not allow_from_session:
        return "suppressed:inside-a-woken-session", None

    subject = (subject or "").strip()
    prompt = prompt or ""
    if not subject or not prompt:
        return "suppressed:usage", None

    kind = kind or "task"
    # A responder-filed await is its own source bucket, so the per-source cap
    # means what it says without the caller having to pass a source.
    source = source or (kind if kind and kind != "task" else "manual")
    priority = priority if priority in ("high", "normal", "low") else "normal"
    cooldown = _env_int("WAKE_COOLDOWN_SEC", 1800) if cooldown_seconds is None else int(cooldown_seconds)
    max_att = _env_int("WAKE_MAX_ATTEMPTS", 2) if max_attempts is None else int(max_attempts)
    if max_att < 1:
        max_att = 1

    if paused():
        return "suppressed:paused", None

    stamp = now()
    existing = row_dict(conn.execute("SELECT * FROM wake WHERE subject=?", (subject,)).fetchone())

    # guard 1 - dedup: one live row per issue.
    if existing is not None and existing["state"] in LIVE_STATES:
        return "deduped", existing["id"]

    if existing is None:
        cur = conn.execute(
            """INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,
                                not_before,state,attempts,max_attempts)
               VALUES(?,?,?,?,?,?,?,NULL,'new',0,?)""",
            (subject, kind, source, prompt, context or "", priority, stamp, max_att),
        )
        row_id = int(cur.lastrowid)
        result = "filed"
    else:
        # A terminal row: revive it. `subject` is UNIQUE, so this is the only
        # way a re-flag can ever mean anything.
        # guard 9 - a subject that has failed max_attempts times is never
        # retried automatically.
        carried = int(existing["attempts"] or 0)
        if existing["state"] not in ("done", "expired"):
            if carried >= max_att:
                return "suppressed:attempts", existing["id"]
        else:
            carried = 0                      # success or abandonment is not a failure

        # guard 2 - cooldown after a release.
        last = _last_release(existing)
        if cooldown > 0 and last is not None and (now_dt() - last) < timedelta(seconds=cooldown):
            until = (now_dt() + timedelta(seconds=cooldown)).isoformat(timespec="seconds")
            conn.execute(
                """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                       created_at=?, not_before=?, state='new', attempts=?, max_attempts=?,
                       claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                       finished_at=NULL, outcome=NULL, cost_usd=NULL
                   WHERE id=?""",
                (kind, source, prompt, context or "", priority, stamp, until, carried,
                 max_att, existing["id"]),
            )
            return "suppressed:cooldown", existing["id"]

        conn.execute(
            """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                   created_at=?, not_before=NULL, state='new', attempts=?, max_attempts=?,
                   claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                   finished_at=NULL, outcome=NULL, cost_usd=NULL
               WHERE id=?""",
            (kind, source, prompt, context or "", priority, stamp, carried, max_att,
             existing["id"]),
        )
        row_id = existing["id"]
        result = "filed"

    # guards 3 and 10 reported at file time: the row is filed either way (the
    # contract says an over-cap row stays `new`), but the caller is told.
    if result == "filed" and release_block(conn) in ("daily-cap", "cost-cap"):
        result = "capped"
    return result, row_id


def _one_line(text, limit: int = 400) -> str:
    """flag prints exactly one line, whatever happened."""
    flat = " ".join(str(text).split())
    return flat[:limit]


def cmd_flag(args) -> int:
    allow = bool(getattr(args, "allow_from_session", False))
    try:
        conn = connect()
        with _tx(conn):
            result, row_id = file_wake(
                conn,
                subject=getattr(args, "subject", None),
                prompt=getattr(args, "prompt", None),
                context=getattr(args, "context", "") or "",
                kind=getattr(args, "kind", "task") or "task",
                source=getattr(args, "source", "") or "",
                priority=getattr(args, "priority", "normal") or "normal",
                cooldown_seconds=getattr(args, "cooldown_seconds", None),
                max_attempts=getattr(args, "max_attempts", None),
                allow_from_session=allow,
            )
        ok = True
    except Exception as exc:                                  # noqa: BLE001
        # A flag must never break its caller - but it must never LIE either. An
        # unexpected failure is reported as `error:...`, never as a suppression,
        # because `suppressed:*` on a broken store reads as a quiet day.
        traceback.print_exc(file=sys.stderr)
        print(f"wake: flag caught {type(exc).__name__}: {exc}", file=sys.stderr)
        result = f"error:{type(exc).__name__}: {_one_line(exc)}"
        row_id, ok = None, False
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps({"ok": ok, "result": result, "id": row_id}) + "\n")
    else:
        sys.stdout.write(_one_line(result) + "\n")
    return 0


# --------------------------------------------------------------------------- #
# the shared writer, kept for sms-responder.py
# --------------------------------------------------------------------------- #
def _file_wake(conn: sqlite3.Connection, *, subject: str, prompt: str, context: str = "",
               kind: str = "task", priority: str = "normal", source: str = "",
               cooldown_seconds: int | None = None,
               max_attempts: int | None = None,
               allow_from_session: bool = False) -> bool:
    """True when a wake row now exists for this subject that did not before.

    Called by sms-responder.py with its own connection. Filing-time guards
    (kill switch, cooldown, attempt ceiling, woken-session refusal) are applied
    here too, so a paused system cannot be woken by a text and a session cannot
    wake itself; a capped day still files (the cap is enforced at claim),
    matching guard 3.
    """
    _ensure(conn)                       # the caller's connection may know no wake tables
    result, _ = file_wake(conn, subject=subject, prompt=prompt, context=context,
                          kind=kind, source=source, priority=priority,
                          cooldown_seconds=cooldown_seconds, max_attempts=max_attempts,
                          allow_from_session=allow_from_session)
    return result in ("filed", "capped")


# --------------------------------------------------------------------------- #
# claim / heartbeat - the release path
# --------------------------------------------------------------------------- #
def _candidates(conn: sqlite3.Connection):
    """New rows that are past their not_before and inside every per-row gate."""
    quiet = night_quiet_active()
    per_source = _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12)
    when = now_dt()
    seen: dict[str, int] = {}
    out = []
    for r in conn.execute(
        """SELECT * FROM wake WHERE state='new' AND attempts < max_attempts
           ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id"""
    ).fetchall():
        nb = parse_dt(r["not_before"])
        if nb is not None and nb > when:
            continue
        if r["priority"] == "low" and quiet:
            continue
        if per_source > 0:
            src = r["source"] or "manual"
            if src not in seen:
                seen[src] = source_releases_last_hour(conn, src)
            if seen[src] >= per_source:
                continue
        out.append(r)
    return out


def _candidates_gated(conn: sqlite3.Connection) -> dict:
    """Why `_candidates` returned nothing, counted per reason. Never raises.

    Exists because the claim path used to answer `blocked_by: null` when the queue was FULL of rows
    that were merely gated - a reading that cannot distinguish "no work" from "work is gated".
    """
    quiet = night_quiet_active()
    per_source = _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12)
    when = now_dt()
    out = {"not_before": 0, "night_quiet": 0, "source_hourly_cap": 0,
           "by_source": {}, "new_rows": 0}
    try:
        rows = conn.execute(
            "SELECT * FROM wake WHERE state='new' AND attempts < max_attempts").fetchall()
        out["new_rows"] = len(rows)
        seen: dict[str, int] = {}
        for r in rows:
            nb = parse_dt(r["not_before"])
            if nb is not None and nb > when:
                out["not_before"] += 1
                continue
            if r["priority"] == "low" and quiet:
                out["night_quiet"] += 1
                continue
            if per_source > 0:
                src = r["source"] or "manual"
                if src not in seen:
                    seen[src] = source_releases_last_hour(conn, src)
                if seen[src] >= per_source:
                    out["source_hourly_cap"] += 1
                    out["by_source"][src] = out["by_source"].get(src, 0) + 1
                    continue
    except Exception as exc:
        out["error"] = "%s: %s" % (type(exc).__name__, exc)
    return out


def cmd_claim(args) -> int:
    conn = connect()
    with _tx(conn):
        blocked = release_block(conn)
        if blocked is not None:
            payload = {"ok": True, "row": None, "blocked_by": blocked}
            sys.stdout.write(json.dumps(payload) + "\n")
            return 0
        cands = _candidates(conn)
        if not cands:
            # NOTHING CLAIMABLE IS NOT THE SAME AS NOTHING GATED. Measured 2026-09-28 19:56Z: with 15
            # rows waiting the claim path answered `blocked_by: null`, which reads as "the queue is
            # empty" - while in truth every row was refused by the per-source hourly cap or a
            # not-before cooldown. A caller that cannot tell those two states apart either burns
            # context investigating or concludes the system is idle.
            gated = _candidates_gated(conn)
            payload = {
                "ok": True,
                "row": None,
                "blocked_by": "night-quiet" if (gated.get("new_rows") and night_quiet_active()
                                                and not gated.get("source_hourly_cap"))
                             else ("row-gates" if gated.get("new_rows") else None),
                "gated": gated,
            }
            sys.stdout.write(json.dumps(payload) + "\n")
            return 0
        row = cands[0]
        lease = _env_int("WAKE_LEASE_SEC", 1200) \
            if getattr(args, "lease_seconds", None) is None else int(args.lease_seconds)
        stamp = now_dt()
        lease_until = (stamp + timedelta(seconds=lease)).isoformat(timespec="seconds")
        conn.execute(
            """UPDATE wake SET state='claimed', claimed_by=?, claimed_at=?, lease_until=?,
                   attempts=attempts+1
               WHERE id=? AND state='new'""",
            (args.by, stamp.isoformat(timespec="seconds"), lease_until, row["id"]),
        )
        _bump_budget(conn, released=1)
        fresh = row_dict(conn.execute("SELECT * FROM wake WHERE id=?", (row["id"],)).fetchone())
    sys.stdout.write(json.dumps({"ok": True, "row": fresh}) + "\n")
    return 0


def cmd_heartbeat(args) -> int:
    conn = connect()
    lease = _env_int("WAKE_LEASE_SEC", 1200) \
        if getattr(args, "lease_seconds", None) is None else int(args.lease_seconds)
    with _tx(conn):
        row = conn.execute("SELECT * FROM wake WHERE id=?", (args.id,)).fetchone()
        if row is None:
            sys.stdout.write(json.dumps({"ok": False, "id": args.id, "error": "no-such-row"}) + "\n")
            return 2
        if row["state"] != "claimed":
            sys.stdout.write(json.dumps(
                {"ok": False, "id": args.id, "error": "not-claimed", "state": row["state"]}) + "\n")
            return 2
        if row["claimed_by"] and args.by and row["claimed_by"] != args.by:
            print(f"wake: row #{args.id} is claimed by {row['claimed_by']!r}, "
                  f"heartbeat from {args.by!r}", file=sys.stderr)
        lease_until = (now_dt() + timedelta(seconds=lease)).isoformat(timespec="seconds")
        conn.execute("UPDATE wake SET lease_until=? WHERE id=?", (lease_until, args.id))
    sys.stdout.write(json.dumps(
        {"ok": True, "id": args.id, "claimed_by": row["claimed_by"],
         "lease_until": lease_until, "extended": True}) + "\n")
    return 0


def cmd_finish(args) -> int:
    conn = connect()
    state = "failed" if args.failed else "done"
    cost = getattr(args, "cost_usd", None)
    with _tx(conn):
        row = row_dict(conn.execute("SELECT * FROM wake WHERE id=?", (args.id,)).fetchone())
        if row is None:
            print(f"wake: no wake row #{args.id}", file=sys.stderr)
            return 2
        conn.execute(
            """UPDATE wake SET state=?, finished_at=?, outcome=?,
                   cost_usd=COALESCE(?, cost_usd), lease_until=NULL WHERE id=?""",
            (state, now(), args.outcome or "", cost, args.id),
        )
        if state == "failed" and row["state"] != "failed":
            _bump_budget(conn, failed=1)
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(
            {"ok": True, "id": args.id, "state": state, "cost_usd": cost}) + "\n")
    else:
        sys.stdout.write(f"#{args.id} -> {state}\n")
    return 0


# --------------------------------------------------------------------------- #
# reap - the recovery path, safe to run twice
# --------------------------------------------------------------------------- #
def do_reap(conn: sqlite3.Connection) -> dict:
    cap = caps_now()
    when = now_dt()
    stamp = when.isoformat(timespec="seconds")
    requeued: list[int] = []
    failed: list[tuple[int, int]] = []

    for row in conn.execute("SELECT * FROM wake WHERE state='claimed'").fetchall():
        lease_until = parse_dt(row["lease_until"])
        claimed_at = parse_dt(row["claimed_at"])
        if lease_until is None:
            # A claim that never recorded a lease (v0 rows, or a crashed writer)
            # is recovered once it is older than one lease.
            if claimed_at is None or claimed_at > when - timedelta(seconds=cap["lease_sec"]):
                continue
        elif lease_until > when:
            continue
        attempts = int(row["attempts"] or 0)
        ceiling = int(row["max_attempts"] or cap["max_attempts"])
        if attempts >= ceiling:
            failed.append((row["id"], attempts))
        else:
            requeued.append(row["id"])

    for row_id in requeued:
        conn.execute(
            """UPDATE wake SET state='new', claimed_by=NULL, claimed_at=NULL,
                   lease_until=NULL WHERE id=?""",
            (row_id,),
        )
    for row_id, attempts in failed:
        conn.execute(
            """UPDATE wake SET state='failed', finished_at=?, lease_until=NULL, outcome=?
               WHERE id=?""",
            (stamp, f"lease expired after {attempts} attempt(s); the attempt cap is reached",
             row_id),
        )
    if failed:
        _bump_budget(conn, failed=len(failed))

    cutoff = (when - timedelta(days=30)).isoformat(timespec="seconds")
    old = [r["id"] for r in conn.execute(
        "SELECT id FROM wake WHERE state='new' AND created_at < ?", (cutoff,)).fetchall()]
    for row_id in old:
        conn.execute(
            "UPDATE wake SET state='expired', finished_at=?, outcome=? WHERE id=?",
            (stamp, "expired: still new after 30 days", row_id),
        )
    return {"ok": True, "requeued": len(requeued), "failed": len(failed), "expired": len(old)}


def cmd_reap(args) -> int:
    conn = connect()
    with _tx(conn):
        out = do_reap(conn)
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(out) + "\n")
    else:
        sys.stdout.write(
            f"reaped: {out['requeued']} back to new, {out['failed']} failed, "
            f"{out['expired']} expired\n")
    return 0


# --------------------------------------------------------------------------- #
# list / stats
# --------------------------------------------------------------------------- #
def cmd_list(args) -> int:
    conn = connect()
    sql = "SELECT * FROM wake"
    params: list = []
    if args.state:
        sql += " WHERE state=?"
        params.append(args.state)
    sql += (" ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id")
    limit = getattr(args, "limit", None)
    if limit is not None and limit > 0:
        sql += " LIMIT ?"
        params.append(limit)
    rows = _rows(conn, sql, tuple(params))
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps({"ok": True, "count": len(rows), "rows": rows}) + "\n")
        return 0
    sys.stdout.write(f"{len(rows)} wake row(s)\n")
    for r in rows:
        sys.stdout.write(
            f"  #{r['id']:<3} {r['state']:<9} {r['priority']:<6} {str(r['source'])[:14]:<14}"
            f" a={r['attempts']}/{r['max_attempts']} {str(r['subject'])[:56]}\n")
        if r["state"] in ("done", "failed", "expired") and r["outcome"]:
            sys.stdout.write(f"        -> {str(r['outcome'])[:90]}\n")
        if r["not_before"] and r["state"] == "new":
            sys.stdout.write(f"        not before {r['not_before']}\n")
    return 0


def stats_payload(conn: sqlite3.Connection) -> dict:
    counts = {s: 0 for s in STATES}
    for r in conn.execute("SELECT state, COUNT(*) n FROM wake GROUP BY state").fetchall():
        counts[r["state"]] = int(r["n"])
    caps = caps_now()
    return {
        "ok": True,
        "day": today_utc(),
        "states": counts,
        "released_today": released_today(conn),
        # A caller that reads only this key must not be able to turn it into throughput.
        "released_today_means": (
            "sessions started, NOT pieces of work: one wake row can be released many"
            " times in a day (file_wake revives a terminal row in place and each source"
            " re-files after its own cooldown). Measured 2026-09-29: 133 releases over 41"
            " distinct ids, the most-re-released subject 20 times. For work done read the"
            " ledger."),
        "failed_today": failed_today(conn),
        "spend_today_usd": spend_today(conn),
        "source_releases_last_hour": source_releases(conn),
        "caps": caps,
        "caps_in_force": caps_in_force(conn),
        "now": now(),
    }


def cmd_stats(args) -> int:
    conn = connect()
    payload = stats_payload(conn)
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0
    counts = payload["states"]
    caps = payload["caps"]
    sys.stdout.write("wake rows: " + " ".join(f"{s}={counts[s]}" for s in STATES) + "\n")
    sys.stdout.write(
        f"released today: {payload['released_today']}/{caps['max_per_day']}"
        f" [SESSIONS started, not work done - one row can be released many times]"
        f"   failed today: {payload['failed_today']}"
        f"   spend today: ${payload['spend_today_usd']:.4f}/${caps['max_usd_per_day']:.2f}\n")
    per_source = payload["source_releases_last_hour"]
    sys.stdout.write(
        "per-source last hour: "
        + (", ".join(f"{k}={v}/{caps['max_per_source_per_hour']}" for k, v in sorted(per_source.items()))
           or "none")
        + f"   cooldown: {caps['cooldown_sec']}s   lease: {caps['lease_sec']}s"
        f"   max attempts: {caps['max_attempts']}   night quiet: "
        f"{'on' if caps['night_quiet'] else 'off'}\n")
    sys.stdout.write("caps in force: " + ("; ".join(payload["caps_in_force"]) or "none") + "\n")
    return 0


# --------------------------------------------------------------------------- #
# pause / resume - guard 6
# --------------------------------------------------------------------------- #
def cmd_pause(args) -> int:
    path = pause_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        f"wake paused {now()} by {getattr(args, 'by', None) or 'manual'}\n"
        "Remove only with `wake.py resume`.\n",
        encoding="utf-8")
    sys.stdout.write(f"paused: {path}\n")
    return 0


def cmd_resume(args) -> int:
    path = pause_file()
    if path.exists():
        path.unlink()
        sys.stdout.write(f"resumed: removed {path}\n")
    else:
        sys.stdout.write(f"not paused: {path} did not exist\n")
    return 0


# --------------------------------------------------------------------------- #
# await / awaits - unchanged behaviour, another component calls consume_await
# --------------------------------------------------------------------------- #
def _expired(row) -> bool:
    if not row["until"]:
        return False
    return str(row["until"])[:10] < today_utc()


def cmd_await(args) -> int:
    conn = connect()
    with _tx(conn):
        conn.execute(
            """INSERT INTO awaited(phone,name,what,sent_at,until,created_by,state)
               VALUES(?,?,?,?,?,?,'active')
               ON CONFLICT(phone) DO UPDATE SET what=excluded.what, name=excluded.name,
                 sent_at=excluded.sent_at, until=excluded.until, state='active'""",
            (inbox.norm(args.phone), args.name, args.what, now(), args.until,
             args.created_by),
        )
    sys.stdout.write(f"awaiting {args.name or args.phone} ({args.phone})\n")
    sys.stdout.write(f"  when they reply: {args.what}\n")
    if args.until:
        sys.stdout.write(f"  stop waiting after: {args.until}\n")
    return 0


def cmd_awaits(args) -> int:
    conn = connect()
    rows = conn.execute("SELECT * FROM awaited ORDER BY sent_at DESC").fetchall()
    active = [r for r in rows if r["state"] == "active" and not _expired(r)]
    sys.stdout.write(f"{len(active)} active await(s)\n")
    for r in active:
        sys.stdout.write(f"  {r['phone']:>14}  {str(r['name'] or '-'):<20} {str(r['what'])[:70]}\n")
    if args.all:
        for r in rows:
            if r not in active:
                sys.stdout.write(f"  ({r['state']}) {r['phone']} {str(r['what'])[:50]}\n")
    return 0


def consume_await(conn: sqlite3.Connection, phone: str):
    """The responder calls this when a reply arrives from someone we awaited."""
    _ensure(conn)
    tail = inbox.norm(phone)
    row = conn.execute("SELECT * FROM awaited WHERE phone=?", (tail,)).fetchone()
    if not row or row["state"] != "active" or _expired(row):
        return None
    conn.execute("UPDATE awaited SET state='consumed' WHERE phone=?", (tail,))
    conn.commit()
    return row


# --------------------------------------------------------------------------- #
def _add_flag_args(parser) -> None:
    parser.add_argument("--subject")
    parser.add_argument("--prompt")
    parser.add_argument("--kind", default="task")
    parser.add_argument("--source", default="")
    # No `choices` on purpose: an argument argparse rejects exits 2, and a flag
    # must exit 0 no matter what. file_wake coerces anything unrecognised.
    parser.add_argument("--priority", default="normal")
    parser.add_argument("--context", default="")
    parser.add_argument("--cooldown-seconds", type=int, default=None)
    parser.add_argument("--max-attempts", type=int, default=None)
    parser.add_argument("--allow-from-session", action="store_true",
                        help="override the woken-session refusal (guard 11)")
    parser.add_argument("--json", action="store_true")


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd")

    s = sub.add_parser("flag"); _add_flag_args(s); s.set_defaults(func=cmd_flag)
    s = sub.add_parser("add"); _add_flag_args(s); s.set_defaults(func=cmd_flag)

    s = sub.add_parser("claim")
    s.add_argument("--by", default="unknown")
    s.add_argument("--lease-seconds", type=int, default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_claim)

    s = sub.add_parser("heartbeat")
    s.add_argument("id", type=int)
    s.add_argument("--by", default="unknown")
    s.add_argument("--lease-seconds", type=int, default=None)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_heartbeat)

    s = sub.add_parser("finish")
    s.add_argument("id", type=int)
    s.add_argument("--outcome", default="")
    s.add_argument("--cost-usd", type=float, default=None)
    s.add_argument("--failed", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_finish)

    s = sub.add_parser("reap"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_reap)

    s = sub.add_parser("list")
    s.add_argument("--state")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_list)

    s = sub.add_parser("stats"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_stats)

    s = sub.add_parser("pause"); s.add_argument("--by", default=None)
    s.set_defaults(func=cmd_pause)
    sub.add_parser("resume").set_defaults(func=cmd_resume)

    s = sub.add_parser("await")
    s.add_argument("phone"); s.add_argument("--name"); s.add_argument("--what", required=True)
    s.add_argument("--until"); s.add_argument("--created-by", default="zabz")
    s.set_defaults(func=cmd_await)

    s = sub.add_parser("awaits"); s.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_awaits)

    return p


def main(argv=None) -> int:
    p = build_parser()
    argv = list(sys.argv[1:]) if argv is None else list(argv)
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        if argv and argv[0] in ("flag", "add"):
            # "flag exits 0 no matter what" includes a malformed call: a caller
            # that mistypes an argument must not be killed by its own flag.
            if "--json" in argv:
                sys.stdout.write(json.dumps(
                    {"ok": False, "result": "suppressed:usage", "id": None}) + "\n")
            else:
                sys.stdout.write("suppressed:usage\n")
            return 0
        code = exc.code
        return code if isinstance(code, int) else 2
    if not getattr(args, "func", None):
        args = p.parse_args(["list"])
    try:
        return args.func(args)
    except sqlite3.Error as exc:
        print(f"wake: database error: {exc}", file=sys.stderr)
        return 2
    except OSError as exc:
        print(f"wake: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
