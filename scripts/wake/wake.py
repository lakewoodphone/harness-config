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
    wake.py finish ID --outcome TEXT [--cost-usd X]
              |  finish ID --failed ...
              |  finish ID --unverified ...      (see THREE OUTCOMES, below)
    wake.py reap [--json]
    wake.py list [--state S] [--limit N] [--include-selftest] [--json]
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

THREE OUTCOMES, NOT TWO: done / failed / unverified. Until 2026-10-02 a row whose
session ran and whose out-file could not be read back was closed `failed` with
the words "the result is unverified" - so the store could not tell a broken
session from broken transport, and the unreadable result consumed one of the
row's `max_attempts` exactly like a crash. Measured on wake #498, 2026-10-02.
Now `finish --unverified` closes such a row in its OWN state, refunds the attempt
(the ambiguity is the transport's fault, not the session's) and, unlike `failed`,
does not increment `wake_budget.failed`. The refund is bounded by the `unverified`
column so an unreadable out-file can never become an unbounded retry loop: after
`WAKE_MAX_UNVERIFIED` (3) unverified releases a re-flag answers
`suppressed:unverified` instead of releasing again. A success clears the count.
A session killed at its bound stays `failed` - that one is a real loss, and its
outcome text says what was lost.

A TEST ROW IS NOT A PRODUCTION FAILURE. The owner-guard test proves the filing
path by writing a real row into the LIVE store and closing it `failed`; on
2026-10-02 that was 139 of the store's 195 `failed` rows and every counter that
read the store called them production failures. `stats`, `list` and the release
path count REAL rows only, and report the test rows on their own line. The frozen
marker is `kind='selftest'` (set at creation by the caller); rows filed before
that marker existed are recognised by the guard test's own subject namespace
(`SMselftest-`). Nothing is deleted or rewritten - the record is append-only.

A WOKEN SESSION MUST NOT RAISE FLAGS. A headless session runs this same CLI, so
a session that misunderstands its task could file a flag, which releases another
session, which files another - unbounded recursion. Therefore: if `WAKE_SESSION`
is set to a non-empty value, **the store layer refuses to file anything** and
returns `suppressed:inside-a-woken-session`, whatever the caller is. The
dispatcher sets it in the environment of every session it launches. An explicit
`--allow-from-session` on `flag`/`add` overrides it for the rare deliberate
case. This lives in `file_wake()` rather than in the CLI so that every caller -
`flag`, `add`, `_file_wake` in sms-responder.py - inherits it.

THE PROJECT FAMILY. project-keepalive must be allowed more than one flag a day
(`max_flags_per_day`), and it makes each extra flag unique with a `#<n>` suffix
(`project:<id>:<day>`, then `#2`, `#3`, ...), because `subject` is UNIQUE.
Evaluated on the exact string, guard 1, guard 2 and guard 9 can NEVER bind on
the 2nd..Nth flag of a day: every one is a brand-new row with attempts=0 and no
release to cool down from. They are therefore evaluated on the FAMILY
`project:<id>:<day>` for PROJECT subjects only - one live row per family, the
family's own filing/release clock for the cooldown, and the family's attempt
ledger. A non-project subject has no family and is byte-for-byte unchanged.
MEASURED 2026-10-14 as the defect this fixes: chumash
`project:chumash:20261013#10` released 03:39:03Z and `#11` at 03:54:04Z, 15
minutes apart against a 1800 s cooldown.

ENVIRONMENT (all read AT CALL TIME, never at import, so tests can set them):
    SMS_INBOX_DB, SMS_INBOX_APP_DB, SMS_INBOX_ENV   - the store (sms-inbox.py)
    WAKE_COOLDOWN_SEC           (1800) guard 2
    WAKE_MAX_PER_DAY          (500)    guard 3  - RELEASE COUNT ceiling. The value in
                                        force comes from the one budget file
                                        (~/.sms-inbox/wake-budget.json) when it exists
    WAKE_MAX_PER_SOURCE_PER_HOUR(12)   guard 4 - raised 2026-09-30: one number, every reader
    WAKE_NIGHT_QUIET            (1)    guard 5
    WAKE_PAUSE_FILE             (~/.sms-inbox/WAKE_PAUSED) guard 6
    WAKE_LEASE_SEC              (1200) guard 7
    WAKE_MAX_ATTEMPTS           (2)    guard 9
    WAKE_MAX_UNVERIFIED         (3)    how many `unverified` outcomes one subject may
                                       collect before a re-flag stops releasing it;
                                       0 disables the bound (see THREE OUTCOMES)
    WAKE_NO_MIGRATE             - set 1 to make connect() READ-ONLY in effect: it
                                       will not CREATE or ALTER anything, so `stats`
                                       can read a store it must not write. Reads
                                       only; a write against an un-migrated table
                                       fails loudly.
    WAKE_MAX_USD_PER_DAY        guard 10 - USD spend ceiling; the OWNER'S 70.00 is
                                        written once, in DEFAULT_MAX_USD_PER_DAY, and
                                        the daily value in force is read from the one
                                        budget file, as wake-dispatch.sh does too
    WAKE_SESSION                - set inside a woken session; refuses every flag
                                  (guard 11, always on)
    WAKE_CLOCK_ISO      - test/ops override for "now" (ISO8601). A time gate
                          that cannot be exercised by a test is not a guard.
    WAKE_ONLY_PROJECT   - aim a release at ONE project: only rows whose subject
                          is `project:NAME:<date>[#n]` (the shape both keepalive
                          sources file). Applied inside _candidates, so every
                          frozen guard still applies.
    WAKE_ONLY_ID        - aim at ONE wake row id (wins over WAKE_ONLY_PROJECT)
    WAKE_ONLY_MATCH     - aim at a substring of subject/context/source/prompt
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
import re
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
    finished_at  TEXT, outcome TEXT, cost_usd REAL,
    unverified   INTEGER NOT NULL DEFAULT 0   -- how many `unverified` outcomes this row has had
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
    "unverified": "INTEGER NOT NULL DEFAULT 0",
}

# The columns section 3 requires. Kept as a list so `stats`-style introspection
# and the tests can assert completeness rather than trust the DDL above.
WAKE_COLUMNS = (
    "id", "subject", "kind", "source", "prompt", "context", "priority",
    "created_at", "not_before", "state", "attempts", "max_attempts",
    "claimed_by", "claimed_at", "lease_until", "finished_at", "outcome", "cost_usd",
    "unverified",
)

STATES = ("new", "claimed", "done", "failed", "unverified", "cancelled", "expired")
LIVE_STATES = ("new", "claimed")
TERMINAL_STATES = ("done", "failed", "unverified", "cancelled", "expired")

MAX_NOT_BEFORE_REASONS = {
    "paused": "the kill switch is on",
    "daily-cap": "the daily release cap is reached",
    "cost-cap": "the daily spend cap is reached",
    "night-quiet": "low-priority releases are outside their window",
    "source-cap": "this source is at its hourly release cap",
    "attempts": "this subject has failed its maximum attempts",
    "unverified": "this subject's result was unreadable too many times",
    "cooldown": "this subject was released recently",
    "usage": "the caller did not supply a subject and a prompt",
    "error": "an internal error was caught so the caller survives",
}


# --------------------------------------------------------------------------- #
# a TEST ROW is not a production failure - the marker and its two predicates
# --------------------------------------------------------------------------- #
# WHY THIS EXISTS. `test-owner-guard.py` proves the filing path end to end by
# writing a REAL row into the LIVE store and closing it `failed` ("the responder
# commits the filing it reports"). Measured here 2026-10-02: 139 of the store's
# 195 `failed` rows were that test's rows, so the headline failure number was
# mostly the instrument auditing itself - the number said nothing about
# production, and every reader of the store repeated it.
#
# THE FROZEN MARKER IS `kind='selftest'`, set at creation time by the caller.
# Rows that already exist were filed before the marker existed, so they are ALSO
# recognised by the guard test's own subject namespace: it builds the subject as
# `owner-text:SMselftest-durable-<epoch>`. Both predicates exclude; neither ever
# deletes or rewrites, because the record is append-only and the evidence that
# the test ran is worth keeping.
#
# WHAT IS EXCLUDED FROM WHAT. `stats`, `list` and the RELEASE PATH read real rows
# only. Excluding test rows from the release path is not tidiness: a selftest row
# left in state `new` is claimable, and claiming one starts a real headless
# session on the desktop to satisfy a test.
SELFTEST_KIND = "selftest"
SELFTEST_SUBJECT_TOKEN = "SMselftest-"
# How many `unverified` outcomes a subject may collect before a re-flag stops
# releasing it. 0 disables the bound (see cmd_finish / file_wake).
DEFAULT_MAX_UNVERIFIED = 3


def is_selftest_row(r) -> bool:
    """True for a row that proves the harness works, not one the harness worked.

    Accepts a sqlite3.Row or a dict. Never raises: when only one field can be
    read the other predicate is simply unknown, and the row defaults to REAL - a
    real row wrongly counted is visible in the number, a real row wrongly hidden
    is not."""
    def field(key):
        try:
            return r[key]
        except Exception:
            pass
        try:
            return (r or {}).get(key)
        except Exception:
            return None

    if str(field("kind") or "").strip().lower() == SELFTEST_KIND:
        return True
    return SELFTEST_SUBJECT_TOKEN in str(field("subject") or "")


def selftest_sql(alias: str = "") -> str:
    """The same predicate in SQL. `alias` is a row qualifier such as `wake.`."""
    return ("(%skind='%s' OR %ssubject LIKE '%%%s%%')"
            % (alias, SELFTEST_KIND, alias, SELFTEST_SUBJECT_TOKEN))


def selftest_reading(conn: sqlite3.Connection) -> dict:
    """What the test rows are, so the excluded number is never a mystery.

    `by_marker` and `by_subject_token` can overlap (a row filed with the marker
    whose subject is also the guard test's); `both` says by how much, so the
    three numbers always add up in the reader's head."""
    by_state: dict[str, int] = {}
    by_marker = by_subject = both = 0
    for r in conn.execute(
            "SELECT state, kind, subject FROM wake WHERE %s" % selftest_sql()).fetchall():
        by_state[r["state"]] = by_state.get(r["state"], 0) + 1
        marker = str(r["kind"] or "").strip().lower() == SELFTEST_KIND
        subject = SELFTEST_SUBJECT_TOKEN in str(r["subject"] or "")
        by_marker += 1 if marker else 0
        by_subject += 1 if subject else 0
        both += 1 if (marker and subject) else 0
    return {
        "rows": sum(by_state.values()),
        "by_state": by_state,
        "by_marker": by_marker,
        "by_subject_token": by_subject,
        "both": both,
        "excluded_from": list(STATES),
        "note": ("test rows are excluded from the counts and from the release path; "
                 "they are NOT deleted - the record is append-only"),
    }


def store_reading(conn: sqlite3.Connection) -> dict:
    """WHERE this reading came from and HOW OLD it is.

    A count with no source and no age is not a reading (the provenance rule this
    system learned the hard way). The newest row is the store's own evidence that
    it is live; a store whose newest row is hours old is not a quiet store, it is
    an unread one."""
    path = str(getattr(inbox, "STORE", "") or os.environ.get("SMS_INBOX_DB", "") or "?")
    row = conn.execute(
        "SELECT id, created_at FROM wake ORDER BY created_at DESC, id DESC LIMIT 1").fetchone()
    newest_at = row["created_at"] if row is not None else None
    newest_id = row["id"] if row is not None else None
    when = parse_dt(newest_at)
    age = None if when is None else max(0, int((now_dt() - when).total_seconds()))
    return {"path": path, "newest_row_id": newest_id, "newest_row_at": newest_at,
            "newest_row_age_seconds": age, "now": now()}


# --------------------------------------------------------------------------- #
# time, environment and the store - everything read AT CALL TIME
# --------------------------------------------------------------------------- #
def _env_str(name: str, default: str) -> str:
    val = os.environ.get(name)
    return default if val is None or val == "" else val


DEFAULT_MAX_PER_DAY = 500

# THE USD SPEND CEILING - the ONLY place the OWNER'S number is written: 70.00/day.
# He set it himself on 2026-09-28 ("we can't have overall more than $70 ... on the
# deepseek API daily"), and owner question #212 was answered on 2026-10-15 "keep
# 70 USD/day ... ONE number in ONE file" - which filed ledger item 285. Item 232 had
# held this constant down at 25.00 "until #212 is settled"; it is settled, so the hold
# is over and 70.00 is restored as the single literal.
#
# THE DAILY VALUE IN FORCE IS NOT THIS CONSTANT. wake-balance.py measures it into
# ~/.sms-inbox/wake-budget.json, clamped to the balance and to this maximum;
# `cap_max_usd_per_day()` below reads that file back, and wake-dispatch.sh reads the
# same file through `wake.py stats --json`. One file, two readers, one number.
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


def _budget_caps():
    """(max_per_day, max_usd_per_day) as the ONE budget file measures them, else (None, None).

    item 285. THE OTHER READERS OF THIS NUMBER: `wake-dispatch.sh` derives its two gates from
    `wake.py stats --json`; `wake-fanout.sh` and `wake-budget-env.sh` render the same file to
    the environment; `autonomy-status.sh` and the owner digest read `stats`. Before this
    function an UNWRAPPED `wake.py` - a shift, a source tick, a shell - reported this module's
    constants while the wrapped dispatcher enforced the file's measured value: two ceilings
    from two sources. Reading the file here is what makes every reader agree.

    The import is lazy on purpose: `wake_budget.configured_max()` resolves its maximum from
    `DEFAULT_MAX_USD_PER_DAY` in THIS module, so a top-level import would be circular.
    """
    try:
        import wake_budget
        doc = wake_budget.read_budget()
        if not doc:
            return (None, None)
        cap = wake_budget.effective_cap(doc)
        return (wake_budget.effective_max_per_day(doc, cap), cap)
    except Exception:
        return (None, None)


def cap_max_per_day() -> int:
    """Guard 3's ceiling: explicit env, else the one budget file, else the constant."""
    if os.environ.get("WAKE_MAX_PER_DAY") not in (None, ""):
        return _env_int("WAKE_MAX_PER_DAY", DEFAULT_MAX_PER_DAY)
    per, _cap = _budget_caps()
    return DEFAULT_MAX_PER_DAY if per is None else int(per)


def cap_max_usd_per_day() -> float:
    """Guard 10's ceiling, resolved the SAME way as guard 3 so they cannot disagree."""
    if os.environ.get("WAKE_MAX_USD_PER_DAY") not in (None, ""):
        return _env_float("WAKE_MAX_USD_PER_DAY", DEFAULT_MAX_USD_PER_DAY)
    _per, cap = _budget_caps()
    return DEFAULT_MAX_USD_PER_DAY if cap is None else float(cap)


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
    # MEASURED 2026-10-18: the default 5 s busy timeout turned a transient
    # `database is locked` into a hard error, and a dispatcher heartbeat that cannot renew its
    # lease kills the shift (three died at 04:17-04:21). The wake store has many writers
    # (sources, fanout, mirror, responder, cost) and WAL cannot make writer-writer free.
    # Waiting is always cheaper here than losing a shift.
    conn.execute("PRAGMA busy_timeout=30000")
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

    The check is against WAKE_COLUMNS, not against a hand-written probe SELECT.
    The probe used to name an arbitrary subset of columns, so a column added to
    WAKE_COLUMNS without also being added to the probe was never migrated on a
    store that already had the table - the exact silent-drift the constant exists
    to prevent (`unverified`, added 2026-10-02).

    WAKE_NO_MIGRATE=1 skips all of this: a status read against a store it must not
    write (another workstream's store, a `mode=ro` copy, the live authority while
    a branch is still being reviewed) then needs no write access at all. It is for
    READS ONLY - a write against a table the migration has not touched fails
    loudly with `no such column`, which is the correct outcome.
    """
    if _env_bool("WAKE_NO_MIGRATE", False):
        return
    try:
        have = {r["name"] for r in conn.execute("PRAGMA table_info(wake)").fetchall()}
    except sqlite3.Error:
        have = set()
    if have and set(WAKE_COLUMNS).issubset(have):
        return
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


# --- LEDGER #151: one writer for the wake store -----------------------------
# Every wake.py write site funnels through _tx() (705, 826, 871, 917, 1007,
# 1136), so a cross-process flock taken BEFORE BEGIN IMMEDIATE serialises all of
# them and removes wake.py-vs-wake.py write contention - the measured source of
# every 'database is locked' / SQLITE_PROTOCOL line in wake-dispatch.log.
# Ordinary sqlite contention was falsified four independent ways (attempts
# 538/548/550/554); the residual is a short SQLITE_BUSY_RECOVERY / SQLITE_PROTOCOL
# window during release/claim bursts that the sqlite busy handler does not cover.
# Readers never take this lock, and the kernel releases flock on process exit, so
# a dead holder cannot wedge the store.
try:
    import fcntl as _fcntl
except ImportError:                      # non-POSIX (dev box / tests)
    _fcntl = None


@contextlib.contextmanager
def _store_lock():
    """Advisory cross-process single-writer lock for the wake store."""
    if _fcntl is None:
        yield
        return
    store = Path(getattr(inbox, "STORE", Path.home() / ".sms-inbox" / "inbox.db"))
    lock_path = store.parent / (store.name + ".waketx.lock")
    try:
        fh = open(lock_path, "a+")
    except OSError:
        yield                            # never block a heartbeat on lock setup
        return
    try:
        _fcntl.flock(fh.fileno(), _fcntl.LOCK_EX)
    except OSError:
        fh.close()
        yield
        return
    try:
        yield
    finally:
        try:
            _fcntl.flock(fh.fileno(), _fcntl.LOCK_UN)
        finally:
            fh.close()


@contextlib.contextmanager
def _tx(conn: sqlite3.Connection):
    """BEGIN IMMEDIATE under the store's single-writer lock: the claim must be
    atomic against a second dispatcher, including one in another process."""
    with _store_lock():
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
        "max_per_day": cap_max_per_day(),
        "max_per_source_per_hour": _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12),
        "max_usd_per_day": cap_max_usd_per_day(),
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
    if released_today(conn) >= cap_max_per_day():
        return "daily-cap"
    spent = spend_today(conn)
    if spent is None:
        # NO MEASUREMENT IS NOT ZERO. Refuse only once volume means the risk is real, so an
        # unreadable cost file cannot silently stop the operation either.
        if released_today(conn) > UNMEASURED_REFUSE_ABOVE:
            return "spend-unmeasured"
    elif spent >= cap_max_usd_per_day():
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
    if spend is None:
        # NO MEASUREMENT IS NOT ZERO - the same rule release_block already
        # applies. This branch used to be a plain `if spend >= cap[...]`, so an
        # unreadable spend raised `TypeError: '>=' not supported between
        # NoneType and float` and took the whole status reader down with it:
        # measured 2026-10-02, with ~/.sms-inbox/wake-cost.jsonl absent,
        # `wake.py stats` exited 1 - and because the dispatcher derives its two
        # ceilings from `stats --json` and refuses to release when it cannot read
        # them, ONE missing cost file stopped every release. A cap that cannot be
        # evaluated is SAID, never crashed on.
        out.append("spend_unmeasured: the day's spend cannot be read "
                   "(no wake-cost.jsonl), so the USD cap cannot fire; "
                   "the release-count cap is still enforced")
    elif spend >= cap["max_usd_per_day"]:
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

# --------------------------------------------------------------------------- #
# THE PROJECT SUBJECT FAMILY - one project, one day, one throttle
# --------------------------------------------------------------------------- #
# WHY THIS EXISTS. project-keepalive deliberately makes each extra flag of a day
# a UNIQUE subject by appending `#<n>` (see its `subject = f"project:{pid}:{today}"`
# plus `#(used + 1)`), because `subject` is UNIQUE and a project is allowed more
# than one flag a day. The cost: guard 1 (dedup), guard 2 (cooldown) and guard 9
# (the attempt ceiling) were all evaluated on the EXACT subject string, so for
# the 2nd..Nth flag of a day no per-subject guard could ever bind - each family
# member was a brand-new row with attempts=0 and no release to cool down from.
# MEASURED 2026-10-14: chumash `project:chumash:20261013#10` released 03:39:03Z
# and `#11` at 03:54:04Z - 15 minutes apart against a 1800 s cooldown - and
# project-keepalive's per-project cooldown is consulted when it FILES, never by
# the store when it RELEASES. The guards therefore key on the FAMILY for project
# subjects only. A non-project subject has no family: `family_key` returns it
# unchanged and every branch reduces to the exact-subject behaviour it had.
_PROJECT_BASE_RE = re.compile(r"^project:[^:\s]+:\d{8}$")
_PROJECT_MEMBER_RE = re.compile(r"^(project:[^:\s]+:\d{8})#\d+$")


def project_family(subject: str) -> str | None:
    """`project:<id>:<utc-day>` for the base subject and for any `#<n>` member,
    else None. This is the trap the day-suffix must not escape."""
    s = (subject or "").strip()
    m = _PROJECT_MEMBER_RE.match(s)
    if m:
        return m.group(1)
    return s if _PROJECT_BASE_RE.match(s) else None


def family_key(subject: str) -> str:
    """The throttle key for a subject: the project family when there is one,
    otherwise the subject unchanged."""
    s = (subject or "").strip()
    return project_family(s) or s


def family_rows_in(conn: sqlite3.Connection, family: str, project: bool) -> list[dict]:
    """Every wake row that shares `family`'s throttle key, oldest first. A
    non-project subject has a family of exactly one: itself."""
    if not project:
        row = row_dict(conn.execute("SELECT * FROM wake WHERE subject=?", (family,)).fetchone())
        return [row] if row is not None else []
    rows = conn.execute(
        "SELECT * FROM wake WHERE subject=? OR subject LIKE ? ORDER BY id",
        (family, family + "#%"),
    ).fetchall()
    out: list[dict] = []
    for raw in rows:
        r = row_dict(raw)
        if r is not None and project_family(str(r["subject"] or "")) == family:
            out.append(r)
    return out


def family_activity(row: dict) -> datetime | None:
    """The family's clock. A FILING counts as well as a release, because the
    whole point of the family key is that the project's own `cooldown_seconds`
    binds between two flags of the same day - and a row sitting `new` (filed but
    not yet claimed) is exactly the state the `#<n>` suffix used to step around."""
    stamps = [_last_release(row), parse_dt(row.get("created_at"))]
    stamps = [s for s in stamps if s is not None]
    return max(stamps) if stamps else None


def family_last_activity(rows: list[dict], project: bool) -> datetime | None:
    """The newest activity in the family. A non-project family keeps the
    release-only clock it always had (byte-for-byte unchanged behaviour)."""
    stamps = []
    for row in rows:
        d = family_activity(row) if project else _last_release(row)
        if d is not None:
            stamps.append(d)
    return max(stamps) if stamps else None


def file_wake(conn: sqlite3.Connection, *, subject: str, prompt: str, context: str = "",
              kind: str = "task", source: str = "", priority: str = "normal",
              cooldown_seconds: int | None = None,
              max_attempts: int | None = None,
              allow_from_session: bool = False,
              defer_on_cooldown: bool = True,
              detail: dict | None = None) -> tuple[str, int | None]:
    """File, dedupe, suppress or cap. Returns (result, row_id). Never raises on
    a guard decision: every decision is one of the four frozen words.

    GUARD 1, GUARD 2 AND GUARD 9 KEY ON THE PROJECT FAMILY (see `family_key`),
    not on the exact subject, so a project-keepalive `#<n>` day-suffix cannot
    step around the dedup, the cooldown or the attempt ceiling. A non-project
    subject has no family and every branch below reduces to the exact-subject
    behaviour it had before. `detail`, when the caller passes a dict, is filled
    with the family a suppression happened inside of - the frozen stdout word is
    unchanged; the name is reported to the caller for stderr/--json."""
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

    # THE FAMILY. For a project subject the guards below are evaluated against
    # `project:<id>:<day>`, so the `#<n>` day-suffix cannot restart them. For any
    # other subject `family == subject` and `family_rows` is the exact row only.
    family = family_key(subject)
    project = project_family(subject) is not None
    family_rows = family_rows_in(conn, family, project)
    # The governing member is the newest row of the family: its attempt ledger
    # and unverified count are the family's, so a fresh `#<n>` cannot reset them.
    governing = family_rows[-1] if family_rows else existing

    # guard 1 - dedup: one live row per issue, per FAMILY. A `#2` filed while the
    # base subject (or any other member) is live is a no-op, not a second session.
    for row in family_rows:
        if row["state"] in LIVE_STATES:
            # item 232: a live UNCLAIMED row that an earlier tick deferred is
            # repaired here, for a source that opted out of deferral. Without
            # this the fresh composition is never seen -- dedup returns before
            # it -- and the row keeps its day-old prompt even though guard 2 can
            # no longer set one. Never while `claimed`: a session is reading it.
            if (not defer_on_cooldown and row["state"] == "new"
                    and row["not_before"]):
                conn.execute(
                    """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                           created_at=?, not_before=NULL
                       WHERE id=? AND state='new'""",
                    (kind, source, prompt, context or "", priority, stamp, row["id"]),
                )
                if detail is not None:
                    detail.update({
                        "guard": "dedup",
                        "refreshed": int(row["id"]),
                        "was_not_before": row["not_before"],
                        "note": ("live unclaimed row had not_before set by an earlier "
                                 "tick; prompt refreshed and not_before cleared "
                                 "(defer_on_cooldown=False source)"),
                    })
            return "deduped", row["id"]

    if governing is None:
        # No row in the family has ever existed: a plain new subject.
        cur = conn.execute(
            """INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,
                                not_before,state,attempts,max_attempts)
               VALUES(?,?,?,?,?,?,?,NULL,'new',0,?)""",
            (subject, kind, source, prompt, context or "", priority, stamp, max_att),
        )
        row_id = int(cur.lastrowid)
        result = "filed"
    else:
        # guard 9 - the FAMILY's attempt ceiling: a family that has failed
        # `max_att` times is never retried automatically. `done`/`expired` reset
        # the ledger (a family that completed is not the family that kept failing).
        carried = int(governing["attempts"] or 0)
        # THE UNVERIFIED BOUND. An `unverified` outcome refunds its attempt (that
        # is the point of the third outcome), so the attempt ceiling cannot bound
        # it; the row's own unverified count can. `done`/`expired` reset the
        # count: a subject that completed is not the subject that kept being
        # unreadable. WAKE_MAX_UNVERIFIED=0 disables the bound.
        unverified = int(governing.get("unverified") or 0)
        if governing["state"] not in ("done", "expired"):
            if carried >= max_att:
                return "suppressed:attempts", governing["id"]
            unver_cap = _env_int("WAKE_MAX_UNVERIFIED", DEFAULT_MAX_UNVERIFIED)
            if unver_cap > 0 and unverified >= unver_cap:
                return "suppressed:unverified", governing["id"]
        else:
            carried = 0                      # success or abandonment is not a failure
            unverified = 0

        # guard 2 - cooldown after a release, keyed on the FAMILY's newest
        # activity so `#<n>` cannot step around the project's own cooldown.
        last = family_last_activity(family_rows, project)
        if cooldown > 0 and last is not None and (now_dt() - last) < timedelta(seconds=cooldown):
            until = (now_dt() + timedelta(seconds=cooldown)).isoformat(timespec="seconds")
            # item 232: a source that declared defer_on_cooldown=False is
            # day-bucketed, so a deferred row is by construction a day-old prompt
            # -- the staleness this option exists to prevent. Leave the terminal
            # row terminal; the next day's subject is a NEW subject and becomes
            # the replacement, composed and delivered inside the same tick.
            if existing is not None and defer_on_cooldown:
                conn.execute(
                    """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                           created_at=?, not_before=?, state='new', attempts=?, max_attempts=?,
                           unverified=?, claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                           finished_at=NULL, outcome=NULL, cost_usd=NULL
                       WHERE id=?""",
                    (kind, source, prompt, context or "", priority, stamp, until, carried,
                     max_att, unverified, existing["id"]),
                )
            if existing is not None and not defer_on_cooldown and detail is not None:
                detail["deferred"] = False
            if detail is not None:
                age = int((now_dt() - last).total_seconds())
                detail.update({
                    "guard": "cooldown",
                    "family": family,
                    "family_row": int(governing["id"]),
                    "last_activity": last.isoformat(timespec="seconds"),
                    "note": (f"suppressed:cooldown inside the project family {family}: "
                             f"wake #{governing['id']} was active "
                             f"{last.isoformat(timespec='seconds')} ({age}s of {cooldown}s ago)"),
                })
            return "suppressed:cooldown", int(existing["id"] if existing is not None else governing["id"])

        if existing is not None:
            # A terminal row for the EXACT subject: revive it (unchanged path).
            # `subject` is UNIQUE, so this is the only way a re-flag can mean
            # anything for that subject.
            conn.execute(
                """UPDATE wake SET kind=?, source=?, prompt=?, context=?, priority=?,
                       created_at=?, not_before=NULL, state='new', attempts=?, max_attempts=?,
                       unverified=?, claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                       finished_at=NULL, outcome=NULL, cost_usd=NULL
                   WHERE id=?""",
                (kind, source, prompt, context or "", priority, stamp, carried, max_att,
                 unverified, existing["id"]),
            )
            row_id = existing["id"]
        else:
            # A NEW member of the family. It CARRIES the family's attempt ledger,
            # so `max_flags_per_day` cannot multiply the attempt ceiling.
            cur = conn.execute(
                """INSERT INTO wake(subject,kind,source,prompt,context,priority,created_at,
                                    not_before,state,attempts,max_attempts,unverified)
                   VALUES(?,?,?,?,?,?,?,NULL,'new',?,?,?)""",
                (subject, kind, source, prompt, context or "", priority, stamp,
                 carried, max_att, unverified),
            )
            row_id = int(cur.lastrowid)
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
    detail: dict = {}
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
                defer_on_cooldown=not bool(getattr(args, "no_defer", False)),
                detail=detail,
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
    # A family-cooldown suppression has to NAME the family release it
    # is inside of, or the caller sees only `suppressed:cooldown` and
    # cannot tell which flag of the day it collided with. stdout keeps
    # the frozen word; the name goes to stderr and into --json.
    if detail.get("note"):
        print(f"wake: {detail['note']}", file=sys.stderr)
    payload = {"ok": ok, "result": result, "id": row_id}
    if detail:
        payload["detail"] = detail
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(payload) + "\n")
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
# --------------------------------------------------------------------------- #
# LEDGER #203: aim a release at one project (or one row) - the selector
# --------------------------------------------------------------------------- #
# WHY HERE AND NOT IN THE DISPATCHER. `_candidates` is the only place a row is
# allowed to become claimable, so a filter that lives here inherits every frozen
# guard - not_before, night quiet, the per-source hourly cap, the attempt cap and
# release_block's daily/cost ceilings - instead of sitting beside them. A
# dispatcher that claimed first and filtered afterwards would take the wrong row
# and then refuse it, which is the row luck this item exists to remove.
#
# INTERFACE (env, read at call time like every other knob here):
#   WAKE_ONLY_PROJECT=NAME  only rows whose subject is `project:NAME:<date>[#n]`
#   WAKE_ONLY_ID=N          only row N
#   WAKE_ONLY_MATCH=TEXT    substring anywhere in subject/context/source/prompt
# Precedence ID, then PROJECT, then MATCH; none set means no selector, i.e. the
# previous behaviour byte for byte.
def _subject_project(subject) -> str:
    s = str(subject or "")
    if not s.startswith("project:"):
        return ""
    return s[len("project:"):].split(":", 1)[0]


def selector() -> tuple[str, str]:
    only_id = _env_str("WAKE_ONLY_ID", "")
    if only_id:
        return ("id", only_id)
    only_project = _env_str("WAKE_ONLY_PROJECT", "")
    if only_project:
        return ("project", only_project)
    only_match = _env_str("WAKE_ONLY_MATCH", "")
    if only_match:
        return ("match", only_match)
    return ("", "")


def row_matches_selector(r, kind: str, value: str) -> bool:
    if not kind:
        return True
    if kind == "id":
        try:
            return int(r["id"]) == int(value)
        except (TypeError, ValueError):
            return False
    if kind == "project":
        return _subject_project(r["subject"]) == value
    hay = " ".join(str(r[k] or "") for k in ("subject", "context", "source", "prompt"))
    return value in hay


def selector_reading() -> dict:
    kind, value = selector()
    return {"kind": kind, "value": value} if kind else {}


def _candidates(conn: sqlite3.Connection):
    """New rows that are past their not_before and inside every per-row gate."""
    quiet = night_quiet_active()
    per_source = _env_int("WAKE_MAX_PER_SOURCE_PER_HOUR", 12)
    when = now_dt()
    seen: dict[str, int] = {}
    sel_kind, sel_val = selector()
    out = []
    for r in conn.execute(
        """SELECT * FROM wake WHERE state='new' AND attempts < max_attempts
           ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id"""
    ).fetchall():
        nb = parse_dt(r["not_before"])
        if nb is not None and nb > when:
            continue
        if not row_matches_selector(r, sel_kind, sel_val):
            continue
        # NEVER RELEASE A TEST ROW. A selftest row left in state `new` is
        # otherwise claimable, and claiming it spends a real headless session on
        # the desktop to satisfy a test - which is also how a test row would turn
        # into a production failure record.
        if is_selftest_row(r):
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
    sel_kind, sel_val = selector()
    out = {"not_before": 0, "night_quiet": 0, "source_hourly_cap": 0,
           "by_source": {}, "new_rows": 0, "selector": selector_reading(),
           "selector_excluded": 0, "selftest_rows": 0}
    try:
        rows = conn.execute(
            "SELECT * FROM wake WHERE state='new' AND attempts < max_attempts").fetchall()
        real_new = 0
        seen: dict[str, int] = {}
        for r in rows:
            # The selector is counted FIRST: with an aim in force, "why did
            # nothing match" must be answered by whether the aim excluded the
            # row, not by a cooldown the row might also have been under.
            if not row_matches_selector(r, sel_kind, sel_val):
                out["selector_excluded"] += 1
                continue
            # A test row is not work waiting. Counting it as "new" is exactly how
            # a store holding nothing but test rows reads as a busy queue.
            if is_selftest_row(r):
                out["selftest_rows"] += 1
                continue
            real_new += 1
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
        # `new_rows` is REAL new rows: a store whose only new rows are test rows is
        # an empty queue, and `selftest_rows` says so separately.
        out["new_rows"] = real_new
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
            sel_kind, sel_val = selector()
            if sel_kind and gated.get("selector_excluded"):
                # An aimed release that matched nothing must say so: "no work"
                # and "no work for the project you aimed at" are different
                # readings, and only the second is this item's subject.
                blocked_by = "selector"
            elif sel_kind and not gated.get("new_rows"):
                blocked_by = None
            else:
                blocked_by = "night-quiet" if (gated.get("new_rows") and night_quiet_active()
                                               and not gated.get("source_hourly_cap")) \
                             else ("row-gates" if gated.get("new_rows") else None)
            payload = {
                "ok": True,
                "row": None,
                "blocked_by": blocked_by,
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
            # 1, not 2: wake-dispatch.sh's contract is "1 = the store itself says we do not hold
            # this row; 2 = transient". A known state must not be reported as a transient fault
            # and left to a string match.
            return 1
        if row["state"] != "claimed":
            sys.stdout.write(json.dumps(
                {"ok": False, "id": args.id, "error": "not-claimed", "state": row["state"]}) + "\n")
            # See above: a known state is 1, not a transient error.
            return 1
        if row["claimed_by"] and args.by and row["claimed_by"] != args.by:
            print(f"wake: row #{args.id} is claimed by {row['claimed_by']!r}, "
                  f"heartbeat from {args.by!r}", file=sys.stderr)
        lease_until = (now_dt() + timedelta(seconds=lease)).isoformat(timespec="seconds")
        conn.execute("UPDATE wake SET lease_until=? WHERE id=?", (lease_until, args.id))
    sys.stdout.write(json.dumps(
        {"ok": True, "id": args.id, "claimed_by": row["claimed_by"],
         "lease_until": lease_until, "extended": True}) + "\n")
    return 0



# A TRANSIENT REFUSAL IS NOT A FAILED SUBJECT. The attempt is spent at CLAIM time, so without this a flake
# that kills a session consumes one of max_attempts and, on the second, ends the subject for good with its
# work silently lost. Measured 2026-09-30: five releases in one twelve-second burst died in about 21 seconds
# with "dsh: QUOTA: Insufficient Balance" while the account answered is_available true, balance 48.94.
_RETRY_AFTER_SEC = 600
_RETRYABLE_SIGNATURES = (
    "quota", "insufficient balance", "rate_limit", "rate limit", "too many requests",
    "429", "502", "503", "service unavailable", "overloaded",
    "timeout", "timed out", "transport", "connection reset", "broken pipe", "connection refused",
)

# THE ONLY SHAPES THAT RETRY: the dispatcher's own failure lines. See the module comment above
# for the measurement (32 of 487 stored outcomes contain a signature inside a SUCCESSFUL
# session's report). These phrases are written by wake-dispatch.sh and by nothing else.
_RETRY_PREFIX_SIGNATURES = (
    "timed out after ",            # the outer bound killed the hop
    "the desktop runner hit its own ",  # the runner's inner bound killed a live session
    "ssh hop failed (rc=",         # the transport died; session's own verdict unknown
    "prompt transfer to ",         # the prompt never arrived; see the carve-out in _retryable_reason
)
# A line that already says the session finished is a RECOVERED hop, never a retry.
_RETRY_PREFIX_EXCLUDES = ("but the session completed", "no session was started",
                          "out-file was recovered")


def _retryable_reason(outcome: str):
    """The matched dispatcher failure shape, or None when this is not a transport loss.

    Reads only the FIRST LINE, because that is the dispatcher's verdict line when there is one;
    everything after it is the session's own report and must never decide a retry.
    """
    text = (outcome or "").strip()
    if not text:
        return None
    first = text.splitlines()[0].lower()
    # A TRANSPORT LOSS BEFORE ANY SESSION EXISTED IS NOT A CONSUMED ATTEMPT.
    # Measured 2026-10-18: the prompt-transfer failure line carries the words "no session was
    # started", and the exclusion below turns that into "never retry" -- so a hop that died
    # before a session was launched still spent the item's attempt. Twenty rows failed this way
    # in one day and ten reached attempts=2 of 2, which is the cap: they are permanently dead,
    # and each one was a work item the owner asked for. The exclusion is correct for a shape that
    # reports on a session which DID run; it is wrong for a copy that never got there, because
    # nothing ran and nothing was spent.
    if first.startswith("prompt transfer to "):
        return "prompt transfer to "
    # The exclusions are searched across the whole text on purpose: a failure line can wrap
    # onto a second line, and "recovered" is checked before any prefix match so a line that
    # already says the session finished can never be retried.
    low = text.lower()
    if any(x in low for x in _RETRY_PREFIX_EXCLUDES):
        return None
    for sig in _RETRY_PREFIX_SIGNATURES:
        if first.startswith(sig) or ("; " + sig) in first:
            return sig.strip()
    return None


def _retryable_reason_loose(outcome: str):
    """UNUSED and deliberately so: the old whole-text search, kept for one reason only.

    It is the record of a rule that was measured wrong, so the next person reading this file
    does not reintroduce it. Do not wire it into finish. If a provider refusal (a quota answer,
    a 503 from the model gateway) should become retryable again, the fix belongs in
    wake-dispatch.sh: have it write a recognisable failure line and add that shape to
    _RETRY_PREFIX_SIGNATURES above, so the decision is made by the code that observed it.
    """
    low = (outcome or "").lower()
    for sig in _RETRYABLE_SIGNATURES:
        if sig in low:
            return sig
    return None


def _selftest_retryable() -> int:
    """Assert the retry rule on the real shapes. Added 2026-10-07 with the dispatcher-vocabulary rule."""
    cases = [
        # retries: dispatcher failure lines
        ("timed out after 2160s (session killed at the OUTER bound; runner self-bound 2100s) after 2100s - LOST: ...", True),
        ("ssh hop failed (rc=1) after 916s, but the session's out-file was recovered (runner exit 0): ...", False),
        ("the desktop runner hit its own 1800s bound and killed the session (exit 124) after 1830s - that is a bound cutting live work", True),
        ("ssh hop failed (rc=255) after 531s; desktop output: ** WARNING: connection is not using a post-quantum key exchange algorithm.", True),
        # never retries: recovered hops
        ("the ssh hop returned rc=1 after 400s, but the session completed (runner exit 0) and its out-file was recovered: ...", False),
        ("the output file could not be copied back (scp rc=1) after 300s, but the session completed (runner exit 0) and its out-file was recovered: ...", False),
        # REVERSED 2026-10-18, and the reversal is the point of the case. This asserted False:
        # a prompt that never arrived was treated as a spent attempt "because no session was
        # started". Measured cost of that reading: 20 rows failed this way in one day and ten
        # reached attempts=2 of 2 -- permanently dead work items -- for a transport error that
        # consumed nothing and produced nothing. Nothing ran, so nothing was spent.
        ("prompt transfer to zabz-tech-ts failed after 2 attempts (scp rc=1): scp: Connection closed ; no session was started", True),
        ("prompt transfer to zabz-tech-ts failed (scp rc=1); no session was started", True),
        # never retries: the agent's own prose, which is what the corpus showed
        ("I ran the guard with a 30 second timeout and it refused as documented. " + "x" * 400, False),
        ("The old port answered connection refused, so the broker was down. " + "y" * 300, False),
        ("The provider returned a 503 twice, so I retried and finished the item. " + "z" * 300, False),
    ]
    fails = 0
    for text, want in cases:
        got = _retryable_reason(text)
        if (got is not None) != want:
            fails += 1
            print("FAIL retry-classifier: %r -> %r (wanted retry=%s)" % (text[:64], got, want))
    print("wake retry-classifier selfcheck: %d cases, %d failed" % (len(cases), fails))
    return 1 if fails else 0


def cmd_finish(args) -> int:
    conn = connect()
    # THREE OUTCOMES. `--failed` wins if both are passed (a caller that says both
    # has said "failed"; the third outcome must never be a quieter way to record a
    # loss). An `unverified` row:
    #   * gets its own state, so the store can tell it from a broken session;
    #   * REFUNDS the attempt (attempts-1, floored at 0) - the ambiguity is the
    #     transport's fault, and the claim already spent the attempt;
    #   * does NOT increment wake_budget.failed, because it is not a failure;
    #   * increments `unverified`, the bound file_wake applies to re-flags, so a
    #     result nobody can read can never retry forever.
    if getattr(args, "failed", False):
        state = "failed"
    elif getattr(args, "unverified", False):
        state = "unverified"
    else:
        state = "done"
    cost = getattr(args, "cost_usd", None)
    with _tx(conn):
        row = row_dict(conn.execute("SELECT * FROM wake WHERE id=?", (args.id,)).fetchone())
        if row is None:
            print(f"wake: no wake row #{args.id}", file=sys.stderr)
            return 2
        why = _retryable_reason(args.outcome or "") if state == "failed" else None
        if why:
            retry_at = (now_dt() + timedelta(seconds=_RETRY_AFTER_SEC)).isoformat(timespec="seconds")
            conn.execute(
                """UPDATE wake SET state='new', claimed_by=NULL, claimed_at=NULL, lease_until=NULL,
                       attempts=MAX(0, attempts-1), not_before=?, outcome=?
                   WHERE id=?""",
                (retry_at, "retryable: %s - attempt refunded, retrying after %ss" %
                 (why, _RETRY_AFTER_SEC), args.id),
            )
            state = "retry"
            sys.stderr.write("wake: #%s transient (%s) - back to new, attempt refunded, retry after %ss\n"
                             % (args.id, why, _RETRY_AFTER_SEC))
        elif state == "unverified":
            conn.execute(
                """UPDATE wake SET state='unverified', finished_at=?, outcome=?,
                       unverified=unverified+1, attempts=MAX(0, attempts-1),
                       cost_usd=COALESCE(?, cost_usd), lease_until=NULL WHERE id=?""",
                (now(), args.outcome or "", cost, args.id),
            )
        else:
            conn.execute(
                """UPDATE wake SET state=?, finished_at=?, outcome=?,
                       unverified=CASE WHEN ?='done' THEN 0 ELSE unverified END,
                       cost_usd=COALESCE(?, cost_usd), lease_until=NULL WHERE id=?""",
                (state, now(), args.outcome or "", state, cost, args.id),
            )
            if state == "failed" and row["state"] != "failed":
                _bump_budget(conn, failed=1)
        fresh = row_dict(conn.execute(
            "SELECT attempts, max_attempts, unverified FROM wake WHERE id=?",
            (args.id,)).fetchone()) or {}
    if getattr(args, "json", False):
        sys.stdout.write(json.dumps(
            {"ok": True, "id": args.id, "state": state, "cost_usd": cost,
             "attempts": fresh.get("attempts"), "max_attempts": fresh.get("max_attempts"),
             "unverified": fresh.get("unverified")}) + "\n")
    elif state == "unverified":
        sys.stdout.write(
            f"#{args.id} -> unverified (attempt refunded: {fresh.get('attempts')}"
            f"/{fresh.get('max_attempts')}; unverified outcome {fresh.get('unverified')}"
            f"/{_env_int('WAKE_MAX_UNVERIFIED', DEFAULT_MAX_UNVERIFIED)}); "
            "not counted as a failure\n")
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
    sel_kind, sel_val = selector()
    include_selftest = bool(getattr(args, "include_selftest", False))
    # A TEST ROW IS NEITHER WORK NOR A FAILURE, so it is not in this listing - the
    # failure list above all - unless --include-selftest asks for it. The exclusion
    # is in SQL, so the LIMIT applies AFTER it: otherwise a few test rows could
    # push real rows out of `--state failed` and the listing would hide exactly
    # what it was asked for. The rows are never deleted; the count of what was
    # hidden is printed, so "no failures" can be read as a fact about production.
    where: list[str] = []
    params: list = []
    if args.state:
        where.append("state=?")
        params.append(args.state)
    if not include_selftest:
        where.append("NOT " + selftest_sql())
    sql = "SELECT * FROM wake"
    if where:
        sql += " WHERE " + " AND ".join(where)
    sql += (" ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, id")
    limit = getattr(args, "limit", None)
    # The selector is applied in the store's own read path so the dry run and the
    # real claim read the same rows through the same filter. The LIMIT is applied
    # AFTER the filter, or an aim would starve on rows it excluded further down.
    if limit is not None and limit > 0 and not sel_kind:
        sql += " LIMIT ?"
        params.append(limit)
    rows = [r for r in _rows(conn, sql, tuple(params))
            if row_matches_selector(r, sel_kind, sel_val)]
    if sel_kind and limit is not None and limit > 0:
        rows = rows[:limit]
    selftest_hidden = 0
    if not include_selftest:
        count_sql = "SELECT COUNT(*) n FROM wake WHERE " + selftest_sql()
        count_params: list = []
        if args.state:
            count_sql += " AND state=?"
            count_params.append(args.state)
        selftest_hidden = int(
            conn.execute(count_sql, tuple(count_params)).fetchone()["n"])
    if getattr(args, "json", False):
        payload = {"ok": True, "count": len(rows), "rows": rows,
                   "selftest_hidden": selftest_hidden}
        if sel_kind:
            payload["selector"] = {"kind": sel_kind, "value": sel_val}
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0
    if sel_kind:
        sys.stdout.write(f"selector: {sel_kind}={sel_val}\n")
    sys.stdout.write(f"{len(rows)} wake row(s)\n")
    for r in rows:
        sys.stdout.write(
            f"  #{r['id']:<3} {r['state']:<9} {r['priority']:<6} {str(r['source'])[:14]:<14}"
            f" a={r['attempts']}/{r['max_attempts']} {str(r['subject'])[:56]}\n")
        if r["state"] in ("done", "failed", "expired", "unverified") and r["outcome"]:
            sys.stdout.write(f"        -> {str(r['outcome'])[:90]}\n")
        if r["not_before"] and r["state"] == "new":
            sys.stdout.write(f"        not before {r['not_before']}\n")
    if selftest_hidden:
        sys.stdout.write(
            f"selftest rows: {selftest_hidden} hidden (kind='{SELFTEST_KIND}' or subject "
            f"containing '{SELFTEST_SUBJECT_TOKEN}') - excluded from this list, never "
            "deleted; pass --include-selftest to see them\n")
    return 0


def _age_human(seconds) -> str:
    if seconds is None:
        return "age unknown"
    s = int(seconds)
    if s < 90:
        return f"{s}s"
    if s < 5400:
        return f"{s // 60}m"
    if s < 172800:
        return f"{s // 3600}h"
    return f"{s // 86400}d"


def stats_payload(conn: sqlite3.Connection) -> dict:
    # REAL ROWS ONLY. The counts come from the store's own rows, with the test
    # rows subtracted - a headline failure number that includes the instrument's
    # own selftest rows is a number about the instrument, not about production
    # (measured 2026-10-02: 139 of 195 `failed` rows were the guard test's).
    counts = {s: 0 for s in STATES}
    for r in conn.execute(
            "SELECT state, COUNT(*) n FROM wake WHERE NOT %s GROUP BY state"
            % selftest_sql()).fetchall():
        counts[r["state"]] = int(r["n"])
    caps = caps_now()
    return {
        "ok": True,
        "day": today_utc(),
        "states": counts,
        "counts_basis": (
            "real rows only: kind='selftest' and subject containing '%s' are excluded "
            "from `states` and reported separately in `selftest`" % SELFTEST_SUBJECT_TOKEN),
        "selftest": selftest_reading(conn),
        "store": store_reading(conn),
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
    sys.stdout.write("wake rows: " + " ".join(f"{s}={counts.get(s, 0)}" for s in STATES) + "\n")
    st = payload["selftest"]
    if st["rows"]:
        by_state = ", ".join(f"{k} {v}" for k, v in sorted(st["by_state"].items()))
        sys.stdout.write(
            f"selftest rows: {st['rows']} ({by_state}) - excluded from every count above"
            f" and from the release path, never deleted"
            f" [kind='{SELFTEST_KIND}' {st['by_marker']}, subject~'{SELFTEST_SUBJECT_TOKEN}'"
            f" {st['by_subject_token']}]\n")
    else:
        sys.stdout.write("selftest rows: 0 (none in this store)\n")
    # An unreadable spend prints as UNMEASURED: `f"{None:.4f}"` raises, and the
    # one line the money guard exists for must not be the line that crashes.
    spend = payload["spend_today_usd"]
    spend_txt = "UNMEASURED" if spend is None else f"${spend:.4f}"
    sys.stdout.write(
        f"released today: {payload['released_today']}/{caps['max_per_day']}"
        f" [SESSIONS started, not work done - one row can be released many times]"
        f"   failed today: {payload['failed_today']}"
        f"   spend today: {spend_txt}/${caps['max_usd_per_day']:.2f}\n")
    per_source = payload["source_releases_last_hour"]
    sys.stdout.write(
        "per-source last hour: "
        + (", ".join(f"{k}={v}/{caps['max_per_source_per_hour']}" for k, v in sorted(per_source.items()))
           or "none")
        + f"   cooldown: {caps['cooldown_sec']}s   lease: {caps['lease_sec']}s"
        f"   max attempts: {caps['max_attempts']}   night quiet: "
        f"{'on' if caps['night_quiet'] else 'off'}\n")
    sys.stdout.write("caps in force: " + ("; ".join(payload["caps_in_force"]) or "none") + "\n")
    sr = payload["store"]
    # PROVENANCE. A count with no source and no age is not a reading.
    sys.stdout.write(
        f"store: {sr['path']}   newest row: #{sr['newest_row_id']} {sr['newest_row_at']} "
        f"({_age_human(sr['newest_row_age_seconds'])} old, read {sr['now']})\n")
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
    parser.add_argument("--no-defer", action="store_true",
                        help="item 232: this source is day-bucketed -- never let the "
                             "cooldown DEFER its row (refresh a live unclaimed row "
                             "instead, and do not re-arm a terminal one)")
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
    s.add_argument("--unverified", action="store_true",
                   help="the session ran but its result could not be read back: the third "
                        "outcome, distinct from failed - the attempt is refunded and the "
                        "row does not count as a failure (see cmd_finish)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_finish)

    s = sub.add_parser("reap"); s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_reap)

    s = sub.add_parser("list")
    s.add_argument("--state")
    s.add_argument("--limit", type=int, default=50)
    s.add_argument("--include-selftest", action="store_true",
                   help="include kind='selftest' rows (and the guard test's "
                        "SMselftest- rows); they are excluded from the listing by default")
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
