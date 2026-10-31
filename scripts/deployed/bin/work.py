#!/usr/bin/env python3
"""work.py - the durable WORK LEDGER: the backlog, who took what, and what is left.

WHY THIS EXISTS. An autonomous session is one-shot: it is started by a server, it works,
it prints a report, and it dies with no memory at all. Many project workstreams have to be
advanced *every day*, forever, by whichever session wakes next. Before this tool, "what is
left" lived in ad-hoc JSON under ~/.wake-projects/ that each worker rewrote wholesale, and
"what was already tried" lived nowhere. Measured consequences in this system:

  * the same item worked, abandoned and worked again across consecutive shifts;
  * a branch pushed by one shift and never merged by any later one;
  * 27 wake rows filed and never run, with no backlog view that could show it (2026-09-28).

This is not the wake queue. The wake queue is a TRANSPORT: "start a session, here is a task
string". The ledger is STATE: "these are the projects, these are their concrete items, this
is what was tried, this is what is left". A session is an EXECUTION OF an item - the item
outlives it.

THE DOMAIN
    project    a standing workstream with its own repo and its own state of play.
    work_item  one concrete thing to do in a project, with a DEFINITION OF DONE that is a
               COMMAND (not an adjective), a state, a priority, and an age.
    attempt    one shift's try at one item: who, when, what they did, the proving command
               and its result, and what is left. Append-only. This is the memory.

STATES
    todo  running  blocked  done  dropped
    A worker moves todo -> running (claim) -> done | blocked | todo (released).
    `blocked` means "a person or an external thing must act"; it MUST name who. A worker
    that is blocked still takes another item - waiting is not a status.

CONCURRENCY. SQLite in WAL mode with a busy timeout, and a LEASE on every claim, so two
sessions can never take the same item and a worker that dies holding one cannot strand it:
`reap` returns expired leases to `todo` and records that it did.

USAGE
    work.py init
    work.py project add --id lpt-website --title "..." --repo /path [--dod "cmd"]
    work.py project list
    work.py add --project ID --title "..." --dod "the command that proves it" \
                [--why TEXT] [--priority 1-9] [--owner-row N]
    work.py next [--project ID] [--json]          what should be worked on, and why
    work.py claim ITEM --by "host:session" [--lease 3600]
    work.py attempt ITEM --by WHO --did "..." --proof "cmd" --result "output line" \
                [--left "..."] [--state done|blocked|todo] [--blocked-on "the owner"]
    work.py done ITEM --by WHO --proof "cmd" --result "..."
    work.py list [--project ID] [--state S] [--limit N] [--json]
    work.py show ITEM [--json]
    work.py owner-row ITEM --owner-row N | --clear
    work.py history [--project ID] [--limit N]
    work.py reap [--json]
    work.py selftest

EXIT CODES. 0 success (including a refusal that is a decision: `claim` on an item another
worker holds prints `held-by-other` and exits 0 - a lease conflict is not an error). 1 usage
error. 2 a store error, reported as `error:<ExceptionClass>: <message>` on stdout with the
traceback on stderr. It is NEVER reported as a benign word: a store that reports success
while writing nothing is exactly how this system dies looking green.

ENVIRONMENT
    WORK_DB   the database path (default ~/work/work.db)
"""
from __future__ import annotations

import argparse
import json
import os
import re
import socket
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
import time
import traceback
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS project (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    repo        TEXT,
    dod         TEXT,
    enabled     INTEGER NOT NULL DEFAULT 1,
    note        TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS work_item (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    project     TEXT NOT NULL,
    title       TEXT NOT NULL,
    why         TEXT,
    dod         TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'todo',
    priority    INTEGER NOT NULL DEFAULT 5,
    owner_row   INTEGER,
    blocked_on  TEXT,
    revisit_at  TEXT,
    not_before  TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    claimed_by  TEXT,
    lease_until TEXT,
    done_at     TEXT,
    source      TEXT
);
CREATE INDEX IF NOT EXISTS idx_work_state   ON work_item(state, priority, created_at);
CREATE INDEX IF NOT EXISTS idx_work_project ON work_item(project, state);

CREATE TABLE IF NOT EXISTS attempt (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    item        INTEGER NOT NULL,
    worker      TEXT NOT NULL,
    started_at  TEXT NOT NULL,
    ended_at    TEXT,
    did         TEXT,
    proof       TEXT,
    result      TEXT,
    left_over   TEXT,
    state_after TEXT,
    exit_code   INTEGER
);
CREATE INDEX IF NOT EXISTS idx_attempt_item ON attempt(item, id);

CREATE TABLE IF NOT EXISTS note (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    at         TEXT NOT NULL,
    kind       TEXT NOT NULL,
    subject    TEXT,
    body       TEXT NOT NULL
);
"""

DEFAULT_DB = Path(os.path.expanduser(os.environ.get("WORK_DB") or "~/work/work.db"))

# The owner-queue database is a DIFFERENT store from this ledger (owner-queue.py's own
# DEFAULT_DB). lint-refs reads it and never writes: it is the live production app DB.
DEFAULT_OQ_DB = os.environ.get(
    "OWNER_QUEUE_DB", "/home/zabz/personal-secretary-mvp/data/secretary.db")

# The owner-queue store is a DIFFERENT database from this ledger, and it has MOVED before.
# On the cloud authority the ledger is /root/work/work.db and the live owner-queue/tasks
# store is /root/authority.db, while DEFAULT_OQ_DB above still names the frozen office-box
# path - which exists on that host as an EMPTY copy (owner_decision_queue: 0 rows,
# tasks: 0 rows). MEASURED 2026-10-13 (item 43): `work.py lint-refs` with no flag read the
# empty copy and reported two LIVE owner-queue rows (#461, #463) as "missing", so the guard
# that exists to catch DEAD blocked-refs was instead telling the next shift to clear a live
# owner row or file a duplicate. Through one hard-coded path, "store is empty" and "row is
# gone" are indistinguishable, so the store is resolved by CONTENT: the first candidate that
# actually CARRIES rows answers. An explicit --owner-queue-db / OWNER_QUEUE_DB is never
# second-guessed.
_OQ_DB_EXTRA_CANDIDATES = (
    "/root/authority.db",
    str(Path(DEFAULT_DB).resolve().parent.parent / "authority.db"),
)

_OQ_DB_RESOLVED = {}


def _oq_db_rows(path):
    """(readable, rows) for one candidate store: owner_decision_queue + tasks. Never raises.

    An unopenable store, or one with neither table, is simply not usable - the difference
    between "no store here" and a store that can actually answer a "missing row" verdict.
    """
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=15)
        try:
            rows = 0
            for tbl in ("owner_decision_queue", "tasks"):
                try:
                    rows += con.execute("SELECT COUNT(*) FROM %s" % tbl).fetchone()[0]
                except sqlite3.Error:
                    pass
            return True, rows
        finally:
            con.close()
    except Exception:
        return False, 0


def resolve_oq_db(explicit=None):
    """The owner-queue/tasks store to read: explicit wins, else the one that CARRIES rows.

    Explicit paths (--owner-queue-db, OWNER_QUEUE_DB, fixtures) are honoured exactly. With
    neither, the default path is tried first; when it is unreadable or holds ZERO rows it is
    not trusted to answer "that row is missing", and the first candidate that holds rows is
    used instead. If no candidate holds rows the default is returned, so the caller reports
    the store it really read instead of inventing a STALE verdict.
    """
    if explicit:
        return explicit
    if None not in _OQ_DB_RESOLVED:
        best = None
        fallback = None
        for cand in (DEFAULT_OQ_DB,) + _OQ_DB_EXTRA_CANDIDATES:
            if fallback is None and Path(cand).exists():
                fallback = cand
            readable, rows = _oq_db_rows(cand)
            if readable and rows > 0:
                best = cand
                break
        _OQ_DB_RESOLVED[None] = best or fallback or DEFAULT_OQ_DB
    return _OQ_DB_RESOLVED[None]

# The WORK ledger carries the same trap as the owner queue above, and it was MEASURED
# on 2026-10-16 (ledger item 462). The wake contract's rule 6 passes
# `--owner-queue-db /root/authority.db` on every claim; a shift that carried that flag
# across to rule 7's close as `--db /root/authority.db` had connect() run SCHEMA against
# the LIVE production authority store - creating empty work_item/attempt/note tables
# inside it - and then answered `error:no-such-item` with exit status 0, so the close
# was recorded nowhere while the shift believed it had closed the item.
#
# So an explicit --db that is demonstrably NOT this ledger is resolved by CONTENT, the
# same rule the owner queue already uses. A path is honoured when it is a real ledger
# (it has a work_item table and is not visibly the owner-queue store) and when it does
# not exist yet - that is what `init`, and a fresh named store, mean. It is redirected
# only when it cannot be a ledger at all (no work_item table), or when it is a store
# that is plainly the OWNER-QUEUE/PRODUCTION one (it carries tasks /
# owner_decision_queue) yet holds zero ledger rows - i.e. the polluted authority.db.
_LEDGER_DB_EXTRA_CANDIDATES = (
    str(Path(DEFAULT_DB).resolve().parent.parent / "authority.db"),
)
_WORK_DB_RESOLVED = {}


def _ledger_rows(path):
    """work_item row count, or None when `path` is not a ledger (or is unreadable).

    Read-only on purpose: a `show` must never write the ledger schema into a database
    that is not this ledger, which is exactly what connect() did to authority.db.
    """
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=15)
        try:
            return con.execute("SELECT COUNT(*) FROM work_item").fetchone()[0]
        finally:
            con.close()
    except Exception:
        return None


def _owner_store_marker(path):
    """True when the store carries the owner-queue / production marker tables."""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=15)
        try:
            names = {r[0] for r in con.execute(
                "SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except Exception:
        return False
    return bool({"owner_decision_queue", "tasks"} & names)


def resolve_work_db(explicit):
    """The work ledger to read/write for an explicit --db that is not this ledger.

    Honours the named path whenever it could be a ledger, and substitutes the first
    candidate that actually carries work_item rows only when the named store cannot be
    one. The substitution is named on stderr, so a shift that carried the owner-queue
    flag into --db sees the redirect instead of a silent `error:no-such-item`.
    """
    if explicit in _WORK_DB_RESOLVED:
        return _WORK_DB_RESOLVED[explicit]
    chosen = explicit
    if Path(explicit).exists():
        rows = _ledger_rows(explicit)
        polluted = (rows == 0 and _owner_store_marker(explicit))
        if rows is None or polluted:
            for cand in (str(DEFAULT_DB),) + _LEDGER_DB_EXTRA_CANDIDATES:
                if cand == explicit:
                    continue
                if _ledger_rows(cand):
                    chosen = cand
                    break
            sys.stderr.write(
                "work.py: %s is not this work ledger (%s); using %s. "
                "--db /root/authority.db names the OWNER QUEUE, not the work ledger - "
                "do not pass it to close/add/show.\n"
                % (explicit, "no work_item table" if rows is None
                   else "0 work_item rows in the owner-queue store", chosen))
    _WORK_DB_RESOLVED[explicit] = chosen
    return chosen


# A reference to an owner-queue row inside the free-text blocked_on. It matches the shapes
# shifts actually write - "owner-queue #206", "owner-queue row #214", "owner-queue row 209",
# "owner_row 5" - and deliberately does NOT match a bare "item 54" or "task 27217": those are
# ledger/engineering references, and reading them as owner-queue rows is the false positive
# that would make this guard useless.
#
# "owner decision #N" was ADDED 2026-10-22 (item 1158), TOGETHER WITH the "owner decision
# row N" and "owner_decision_queue row N" spellings. SEVEN prod-db-sync/integrate items
# (753, 811, 817, 823, 864, 865, 873) sat blocked with blocked_on = "owner decision #868"
# after row 868 was RESOLVED, while lint-refs reported 0 stale and claim-next hid them:
# the regex named queue/row shapes but not the decision shape shifts actually wrote.
_OQ_REF_RE = re.compile(
    r"(?:owner[\s_-]*(?:queue|decision)(?:[\s_-]*queue)?\s*(?:row\s*)?|"
    r"owner[\s_-]*row\s*)#?\s*(\d+)", re.I)

# A reference to an engineering TASK (the production store's `tasks` table) inside
# blocked_on. It matches the shapes shifts write - "task 27217", "engineering task 27217",
# "task #27233" - and deliberately does NOT match an owner-queue ref or a bare "item 54".
_TASK_REF_RE = re.compile(r"(?:engineering\s+)?task\s*#?\s*(\d+)", re.I)

# A task in one of these states can never release a block: it is finished or abandoned.
# open/in_progress/in-progress/blocked/pending/paused are live states and do NOT warn.
_TASK_TERMINAL = {"done", "completed", "closed", "cancelled", "canceled"}

# A LEDGER item in one of these states can never release a block either. `dropped` is here
# because an abandoned item will never act; `done` is the item-213 case.
_LEDGER_TERMINAL = {"done", "dropped"}

# A reference to a LEDGER item (a work_item in THIS store) inside blocked_on - but ONLY when
# the free text declares it as the DEPENDENCY, never on a bare "item N". The shapes shifts
# write are "blocked on item 60", "Prerequisite item 60 must land first", "must wait for
# item 207", "gated by item 90".
#
# A BARE `item\s*(\d+)` IS A FALSE-POSITIVE MACHINE, and that was MEASURED on the live
# ledger 2026-10-15 rather than imagined: item 20's blocker says "so item 20 DoD clause 2
# cannot currently be re-proven" (a self-reference in prose), and item 120's says "no
# per-phone broker credential (item 90: Token empty in every appsettings, must be issued
# server-side ...)" (an explanatory parenthetical), while item 184's "revocation must wait
# for item 207" is the one real dependency - and 207 is itself still blocked. Matching any
# `item N` would flag 20 and 120 as stale and, through reap, re-queue work whose blocker is
# untouched. So the lead-in phrase is required.
_ITEM_DEP_RE = re.compile(
    r"(?:blocked\s+on|blocked\s+by|gated\s+by|wait(?:ing)?\s+(?:on|for)|waits?\s+on|"
    r"depends?\s+on|prerequisite|pending\s+on)\s*:?\s*(?:ledger\s+)?item\s*#?\s*(\d+)", re.I)

# A reference to a LEDGER item in ANY shape inside blocked_on - "housekeeping item 318",
# "item 207", "blocked on item 60". Unlike _ITEM_DEP_RE it needs NO lead-in phrase, and that is
# deliberate because it is read in the OPPOSITE direction: _ITEM_DEP_RE feeds the STALE verdict,
# where a false match RELEASES live work, while THIS one only SUPPRESSES an owner-queue stale
# verdict (see _stale_oq_refs), where a false match leaves the block exactly as it is. Measured
# on the live ledger 2026-10-16 (item 433): item 184 declares its real gate as "housekeeping item
# 318 (repo-capable GitHub replacement), then the owner GitHub session" - a shape _ITEM_DEP_RE
# does not match - and item 207 declares its gate as "Related: item 184". Both kept a DECIDED
# owner_row 502 while LIVE housekeeping item 318 (state todo) actually held them.
_ITEM_ANY_RE = re.compile(r"\bitem\s*#?\s*(\d+)", re.I)


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def whoami(override: str | None = None) -> str:
    """The name this worker records itself under.

    `--by` exists because a DRIVER starts a session and needs that session's writes to arrive
    under a STABLE handle it already knows, so it can reap the lease if the session dies
    silently - rather than a fresh host:pid which no other process can predict. A session
    running the CLI itself leaves it unset and gets host:pid.
    """
    if override:
        return override
    try:
        host = socket.gethostname()
    except Exception:
        host = "unknown"
    return "%s:%d" % (host, os.getpid())


def connect(db: Path) -> sqlite3.Connection:
    db.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(str(db), timeout=10.0)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA journal_mode=WAL")
    c.execute("PRAGMA busy_timeout=10000")
    c.execute("PRAGMA foreign_keys=ON")
    c.executescript(SCHEMA)
    _migrate(c)
    return c


def _migrate(c: sqlite3.Connection) -> None:
    """Bring an EXISTING store up to the current schema.

    SCHEMA only ever runs CREATE TABLE IF NOT EXISTS, so a column added to the literal
    never reaches a store that already exists - which is exactly how `revisit_at` (item
    145) would have been silently absent from the live ledger while claiming to be there.
    ALTER here, then BACKFILL: a blocked row that was never given a revisit time is
    OVERDUE for triage, not exempt, so it is stamped due now instead of left NULL where
    nothing will ever look at it again.
    """
    cols = {r[1] for r in c.execute("PRAGMA table_info(work_item)")}
    if "revisit_at" not in cols:
        c.execute("ALTER TABLE work_item ADD COLUMN revisit_at TEXT")
        c.execute("UPDATE work_item SET revisit_at=? "
                  "WHERE state='blocked' AND revisit_at IS NULL", (now(),))
        c.execute("UPDATE work_item SET blocked_on=? "
                  "WHERE state='blocked' AND (blocked_on IS NULL OR blocked_on='')",
                  ("untyped: block predates item 145 - name the person or external thing",))
        c.commit()

    # ITEM 1440 (measured 2026-10-31): a TODO item may name a UTC time before which claim-next
    # must not hand it out. Item 1436's DoD named the 03:00-03:30Z window; two shifts claimed it
    # before the window opened, released it, and produced nothing. `revisit_at` is read only for
    # blocked rows, so a date gate on todo work had nowhere to live. ALTER only: existing rows
    # stay NULL, which means "eligible now", so no live item changes behaviour.
    if "not_before" not in cols:
        c.execute("ALTER TABLE work_item ADD COLUMN not_before TEXT")
        c.commit()

    # Item 278: `--revisit` advertises a relative offset ("+7d") but older writes stored it
    # VERBATIM, and the due read then compared that text to an ISO stamp - "+2d" sorts below
    # every date, so the block was permanently past due. Rewrite each such row ONCE to the
    # absolute stamp it always meant, anchored at its own last write. Idempotent: after this
    # runs no blocked row matches the offset form, so an already-clean store is not touched.
    try:
        _rel = c.execute("SELECT id, revisit_at, updated_at, created_at FROM work_item "
                         "WHERE state='blocked' AND revisit_at IS NOT NULL").fetchall()
    except sqlite3.Error:
        _rel = []
    _fixed = 0
    for _r in _rel:
        _resolved = parse_revisit(_r["revisit_at"], _r["updated_at"] or _r["created_at"])
        if _resolved != _r["revisit_at"]:
            c.execute("UPDATE work_item SET revisit_at=? WHERE id=?", (_resolved, _r["id"]))
            _fixed += 1
    if _fixed:
        c.commit()

    # Item 263: the attempt table records the exit code its proof command RETURNED, so an
    # outcome is stored at close time instead of being re-derived from free text later. An
    # existing store gets the column by ALTER; attempt rows that predate this stay NULL and
    # work-outcomes.py keeps deriving them, so nothing already written is rewritten.
    acols = {r[1] for r in c.execute("PRAGMA table_info(attempt)")}
    if "exit_code" not in acols:
        c.execute("ALTER TABLE attempt ADD COLUMN exit_code INTEGER")
        c.commit()


def revisit_default() -> str:
    """When a block must be looked at again if nobody has unblocked it by then."""
    days = int(os.environ.get("WORK_REVISIT_DAYS", "7") or "7")
    return (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")


_REVISIT_OFFSET_RE = re.compile(r"^\s*([+-])?\s*(\d+)\s*([a-z]+)?\s*$", re.I)


def _iso_dt(text):
    """A timezone-aware UTC datetime for an ISO stamp, or None when it cannot be read."""
    if not text:
        return None
    try:
        dt = datetime.fromisoformat(str(text).strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def parse_revisit(value, anchor=None):
    """An ABSOLUTE UTC stamp for a revisit time, or None when there is nothing to read.

    THE DEFECT THIS FIXES (item 278, measured 2026-10-15): `--revisit` advertises a
    relative offset - its own help text says "default +7d" - but the value was stored
    VERBATIM. `_blocked_due` then compared that text against an ISO stamp with SQLite's
    string ordering, where '+' (0x2b) sorts below every digit: a stored "+2d"/"+4d"/"+5d"
    is <= ANY date from 0..9, so a blocked item given a relative revisit was reported due
    at EVERY --at date, forever. Three live rows (80/165/184) sat permanently past due and
    pushed genuinely due items off the list.

    An absolute stamp is returned UNCHANGED so nothing already correct is rewritten; only a
    bare relative offset is anchored. The anchor is the row's own last write (see
    _blocked_due and _migrate), so a legacy "+4d" means "four days after it was blocked",
    not "four days after today" - the latter would silently move the revisit on every read.
    A bare number with neither sign nor unit is not something we can anchor, so it is left
    alone and the unreadable-time policy (due NOW, never hidden) takes over downstream.
    """
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    m = _REVISIT_OFFSET_RE.match(text)
    if not m:
        return text
    sign, digits, unit = m.group(1), m.group(2), (m.group(3) or "").lower()
    if sign is None and not unit:
        return text
    n = int(digits) * (-1 if sign == "-" else 1)
    if unit.startswith("w"):
        delta = timedelta(weeks=n)
    elif unit.startswith("h"):
        delta = timedelta(hours=n)
    elif unit.startswith("m"):
        delta = timedelta(minutes=n)
    else:
        delta = timedelta(days=n)
    base = _iso_dt(anchor) or datetime.now(timezone.utc)
    return (base + delta).strftime("%Y-%m-%dT%H:%M:%SZ")


def _blocked_due(c: sqlite3.Connection, at: str | None = None):
    """Every blocked item whose revisit time has passed (or was never set).

    A NULL revisit_at has no future time at which it becomes due, so it is treated as
    due NOW: a block nobody is ever prompted to revisit is work disappearing quietly,
    which is the failure mode item 145 exists to end.

    Item 278: the comparison happens in PYTHON on the RESOLVED time, not as SQL text. A
    stored relative offset ("+2d") sorted below every ISO date under SQLite's string
    ordering, so a relative revisit was judged permanently past due; resolving here also
    repairs a row written by an older work.py or by raw SQL, regardless of _migrate. The
    revisit_at reported is the absolute time actually compared, with the original kept as
    revisit_raw when they differ, so the decision surface shows what it decided on. An
    unreadable or unset time is due NOW, never hidden: a block nobody can be prompted
    about is work disappearing quietly.
    """
    at_s = at or now()
    at_dt = _iso_dt(at_s)
    rows = c.execute(
        "SELECT id, project, title, priority, blocked_on, revisit_at, updated_at, created_at "
        "FROM work_item WHERE state='blocked'").fetchall()
    due = []
    for r in rows:
        eff = parse_revisit(r["revisit_at"], r["updated_at"] or r["created_at"])
        eff_dt = _iso_dt(eff)
        if eff is None or eff_dt is None:
            due.append((0, r["priority"], "", r, eff))
            continue
        if at_dt is not None:
            if eff_dt > at_dt:
                continue
        elif eff > at_s:
            continue
        due.append((1, r["priority"], eff, r, eff))
    due.sort(key=lambda x: (x[0], x[1], x[2]))
    result = []
    for _, _, _, r, eff in due:
        row = dict(r)
        if eff is not None and eff != row["revisit_at"]:
            row["revisit_raw"] = row["revisit_at"]
            row["revisit_at"] = eff
        result.append(row)
    return result


def out(word: str, **kw) -> int:
    """One machine-readable result word per call. Never raises.

    Exit status: 0 for a result, 2 for an `error:` result - a call that exits 0
    changed something or answered something; see the note below.
    """
    if kw:
        print(word + " " + json.dumps(kw, sort_keys=True))
    else:
        print(word)
    # An `error:` result is NOT a result. Until 2026-10-16 this returned 0 for every word,
    # so `work.py close <id>` on an id that does not exist printed `error:no-such-item` and
    # exited 0 - and a shift that read the exit status believed a close had landed that
    # never happened. MEASURED as ledger item 470: the redirect fix for item 462 removed
    # the wrong-STORE half of that silence, this removes the wrong-ID half. cmd_edit already
    # refused at exit 2 for exactly this reason, so 2 is the house word for "your write did
    # nothing". `nothing-todo` and every success word still exit 0.
    return 2 if word.startswith("error:") else 0


def lease_expired(row: sqlite3.Row) -> bool:
    if not row["lease_until"]:
        return True
    return row["lease_until"] <= now()


# ---------------------------------------------------------------- verbs

def cmd_init(a) -> int:
    c = connect(Path(a.db))
    c.close()
    return out("initialised", db=str(Path(a.db)), at=now())


def cmd_project_add(a) -> int:
    c = connect(Path(a.db))
    t = now()
    c.execute(
        "INSERT INTO project(id,title,repo,dod,enabled,note,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, repo=excluded.repo, "
        "dod=excluded.dod, enabled=excluded.enabled, note=excluded.note, updated_at=excluded.updated_at",
        (a.id, a.title, a.repo, a.dod, 0 if a.disabled else 1, a.note, t, t))
    c.commit()
    return out("project-ok", id=a.id, enabled=(not a.disabled))


def cmd_project_list(a) -> int:
    c = connect(Path(a.db))
    rows = c.execute(
        "SELECT p.id, p.title, p.repo, p.enabled, "
        "(SELECT COUNT(*) FROM work_item w WHERE w.project=p.id AND w.state='todo')    AS todo, "
        "(SELECT COUNT(*) FROM work_item w WHERE w.project=p.id AND w.state='running') AS running, "
        "(SELECT COUNT(*) FROM work_item w WHERE w.project=p.id AND w.state='blocked') AS blocked, "
        "(SELECT COUNT(*) FROM work_item w WHERE w.project=p.id AND w.state='done')    AS done "
        "FROM project p ORDER BY p.enabled DESC, p.id").fetchall()
    if a.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    if not rows:
        print("no projects registered")
        return 0
    print("%-22s %-3s %4s %7s %7s %5s  %s" % ("PROJECT", "on", "todo", "running", "blocked", "done", "TITLE"))
    for r in rows:
        print("%-22s %-3s %4d %7d %7d %5d  %s" % (
            r["id"], "yes" if r["enabled"] else "no", r["todo"], r["running"], r["blocked"], r["done"],
            (r["title"] or "")[:52]))
    return 0


def _kwargs_from_json(a) -> None:
    """Fill the add-arguments from a JSON file. --from-json is the quoting-safe path: `--dod` is a shell
    command and shell quoting mangles it (measured twice, journal L3684)."""
    path = getattr(a, "from_json", None)
    if not path:
        return
    import json as _json
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = _json.loads(raw)
    for key in ("project", "title", "dod", "why", "priority", "owner_row", "source",
                "not_before"):
        attr = "owner_row" if key == "owner_row" else key
        if getattr(a, attr, None) in (None, False) and key in data:
            setattr(a, attr, data[key])


def cmd_add(a) -> int:
    c = connect(Path(a.db))
    proj = c.execute("SELECT id FROM project WHERE id=?", (a.project,)).fetchone()
    if not proj:
        # MEASURED 2026-10-28 (item 807): the single "unknown-project for a project that
        # exists" was a TRANSPOSED id - the call passed kosher-filter-ai for
        # kosher-ai-filter (session d9fc0881 seq 2848) - while the bare hint sent the shift
        # hunting a state change for four days. Name the near miss instead of the mystery.
        import difflib
        known = [r["id"] for r in c.execute("SELECT id FROM project ORDER BY id")]
        near = (difflib.get_close_matches(str(a.project), known, n=3, cutoff=0.6)
                if a.project else [])
        return out("error:unknown-project", project=a.project, did_you_mean=near,
                   hint="register it first: work.py project add --id %s --title ..." % a.project)
    t = now()
    # DEDUPE, BECAUSE THE OWNER'S DEFINITION OF STUPID IS EXACTLY THIS:
    # "if it's stupid and it works the same project 50 times and each time it's already a little
    # doing that project or it wasn't necessary, then it's stupid" (2026-09-28). A second copy of
    # an open item creates a second shift doing the same work, so the filing is refused and the
    # EXISTING id is returned - the caller is not left guessing which one to take. `--allow-dupe`
    # is the deliberate override, and it has to be typed on purpose.
    dup = c.execute(
        "SELECT id, state, title FROM work_item WHERE project=? AND state IN ('todo','running','blocked') "
        "AND lower(trim(title)) = lower(trim(?)) ORDER BY id LIMIT 1",
        (a.project, a.title)).fetchone()
    if dup and not a.allow_dupe:
        return out("already-filed", id=dup["id"], state=dup["state"], project=a.project,
                   hint="pass --allow-dupe only if this is genuinely a second, different piece of work")
    # ITEM 1440: an optional UTC stamp before which this item must not be handed out. It is
    # normalized on write by the same parser the blocked revisit uses, so "+3h" is stored as
    # the absolute time it names and every stored value sorts chronologically.
    not_before = parse_revisit(getattr(a, "not_before", None))
    cur = c.execute(
        "INSERT INTO work_item(project,title,why,dod,state,priority,owner_row,not_before,"
        "created_at,updated_at,source) "
        "VALUES(?,?,?,?,'todo',?,?,?,?,?,?)",
        # MEASURED 2026-10-15 (item 361): `--priority` is advertised as optional and the
        # schema defaults it to 5, but this line did int(None) whenever the flag was
        # omitted, so `add --project X --title Y --dod Z` died with a TypeError traceback
        # instead of filing. The default is applied HERE rather than in argparse because
        # `_kwargs_from_json` fills `priority` only when the attribute is None/False, and
        # a parser default of 5 would silently out-rank the JSON value.
        (a.project, a.title, a.why, a.dod,
         int(a.priority) if a.priority is not None else 5,
         a.owner_row, not_before, t, t, a.source))
    c.commit()
    return out("item-filed", id=cur.lastrowid, project=a.project,
               priority=int(a.priority) if a.priority is not None else 5)


_WS_RE = re.compile(r"\s+")


def _norm_text(value):
    """A title / did text with case and runs of whitespace flattened, for identity."""
    return _WS_RE.sub(" ", (value or "").strip()).lower()


def _done_title_dupe(c, item):
    """The done item in the SAME project whose title this item repeats, or None.

    MEASURED (item 997): the live ledger carries items whose exact work was already
    closed `done` in the same project -- six copies of "THE DAILY WALK", five of
    "Roadmap supply", and the D1/F0 families. A shift handed one of those spends a
    whole lease re-doing finished work, and the ledger cannot tell it so. The title is
    the only key the table has for "the same work", so it is compared case- and
    whitespace-insensitively and WITHIN the project: two projects may legitimately
    share a phrase. (item 997)
    """
    r = c.execute("SELECT project, title, state FROM work_item WHERE id=?",
                  (item,)).fetchone()
    if not r or r["state"] == "done":
        return None
    return c.execute(
        "SELECT id, title, done_at FROM work_item WHERE project=? AND state='done' "
        "AND id<>? AND lower(trim(title))=lower(trim(?)) ORDER BY id LIMIT 1",
        (r["project"], item, r["title"])).fetchone()


def _done_title_dupes(c, project=None):
    """Every live item whose title a done item in its project already carries."""
    sql = ("SELECT w.id, w.project, w.state, w.title, "
           "(SELECT d.id FROM work_item d WHERE d.project=w.project AND d.state='done' "
           " AND d.id<>w.id AND lower(trim(d.title))=lower(trim(w.title)) "
           " ORDER BY d.id LIMIT 1) AS done_item, "
           "(SELECT d.done_at FROM work_item d WHERE d.project=w.project AND d.state='done' "
           " AND d.id<>w.id AND lower(trim(d.title))=lower(trim(w.title)) "
           " ORDER BY d.id LIMIT 1) AS done_at "
           "FROM work_item w WHERE w.state IN ('todo','running','blocked') "
           "AND EXISTS (SELECT 1 FROM work_item d WHERE d.project=w.project AND d.state='done' "
           " AND d.id<>w.id AND lower(trim(d.title))=lower(trim(w.title)))")
    params = []
    if project:
        sql += " AND w.project=?"
        params.append(project)
    sql += " ORDER BY w.id"
    return [dict(r) for r in c.execute(sql, params).fetchall()]


def _pick_next(c, project=None):
    """The selection rule, stated so it can be argued with.
    Priority first (1 is most urgent). Then strict fairness: the project whose OLDEST
    todo item is oldest goes first, so no project starves behind a busy one. Then the
    item's own age. A `running` item whose lease has expired is treated as todo - a
    worker that died must not take its item with it."""
    # ITEM 1445 (2026-10-31): selection does NOT filter on a done item's title.
    # MEASURED: roadmap-supply re-files the renewable authoring item under the SAME title
    # every cycle (110 -> 151 -> ... -> 1418), so a title match is the normal shape of
    # fresh work, not evidence of a duplicate. The old exclusion made claim-next answer
    # nothing-todo over a live todo row, starving the roadmap until a shift ran
    # `claim <id> --allow-done-dupe` by hand. The dupe is ADVISORY now: _done_title_dupes
    # still reports it and cmd_claim_next attaches it to the claimed item. The explicit
    # `claim` verb keeps its item-997 refusal (--allow-done-dupe), because that is a human
    # override of a warning, not selection of work.
    where = ["w.state='todo'"]
    args = []
    # ITEM 1440: a todo item carrying not_before is invisible to selection until that UTC
    # stamp has passed. NULL/'' is eligible immediately - every row that predates the column.
    # The comparison is text-vs-text; every write below normalizes to YYYY-MM-DDTHH:MM:SSZ,
    # so the ordering is chronological.
    where.append("(w.not_before IS NULL OR w.not_before='' OR w.not_before<=?)")
    args.append(now())
    if project:
        where.append("w.project=?")
        args.append(project)
    q = ("SELECT w.*, p.title AS project_title, p.repo AS repo "
         "FROM work_item w JOIN project p ON p.id=w.project "
         "WHERE " + " AND ".join(where) + " "
         "ORDER BY w.priority ASC, (SELECT MIN(created_at) FROM work_item x "
         "WHERE x.project=w.project AND x.state='todo') ASC, w.created_at ASC LIMIT 1")
    return c.execute(q, args).fetchone()


def cmd_owner_row(a) -> int:
    """Attach (or clear) an owner-queue row reference on an item that ALREADY EXISTS.

    WHY (item 369): `--owner-row` lived only on `add`, so backfilling a structured
    owner-queue ref onto a live item meant hand-editing the ledger with raw sqlite -
    the same path that let item 363's ref end up prose-only and invisible to
    _stale_oq_refs, and therefore to the claim-next nothing-todo warning. A ref set
    here writes exactly the field lint-refs reads, so the guard sees it immediately.
    """
    c = connect(Path(a.db))
    r = c.execute("SELECT id, project, owner_row FROM work_item WHERE id=?",
                  (a.item,)).fetchone()
    if not r:
        c.close()
        return out("error:no-such-item", id=a.item)
    val = None if getattr(a, "clear", False) else a.owner_row
    c.execute("UPDATE work_item SET owner_row=?, updated_at=? WHERE id=?",
              (val, now(), a.item))
    c.commit()
    c.close()
    return out("owner-row-set", item=a.item, owner_row=val, previous=r["owner_row"])


# `blocked_on` is EDITABLE because a stale block is a CORRECTION, not a new decision.
# MEASURED 2026-10-18: three blocked items (32, 366, 323) cite owner rows that are no longer pending,
# and two are not waiting on a person at all (526 was moved to the business queue; 323's real gate is
# a date). The only way to say so was a hand-written UPDATE against the live ledger, which bypasses
# the note trail this verb exists to keep.
# THREE PLACES MUST AGREE - this list, the change branch below, and the ALWAYS-FULL column list in
# the UPDATE. Two earlier attempts failed because they changed the first two and not the third: the
# row was reported edited, the note trail was written, and NOTHING was stored.
_EDITABLE_FIELDS = ("title", "dod", "why", "priority", "blocked_on", "not_before")


def _edit_from_json(a) -> None:
    """Fill the edit-arguments from a JSON file, the quoting-safe path `add` already has.

    Same MEASURED failure as `add --from-json`: `--dod` is a shell command with quotes
    inside it, and text pushed through pwsh -> ssh -> bash has been mangled twice. A DoD
    that arrives as chr() soup looks like a bar and is worse than none.
    """
    path = getattr(a, "from_json", None)
    if not path:
        return
    import json as _json
    raw = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
    data = _json.loads(raw)
    for key in _EDITABLE_FIELDS:
        if getattr(a, key, None) in (None, False) and key in data:
            setattr(a, key, data[key])


def cmd_edit(a) -> int:
    """Correct a stored field on an item that already exists, KEEPING the old value.

    WHY (item 361): this tool exposed add/close/owner-row/attempt but no way to fix a
    stored `dod`, so correcting item 165's unmeasurable DoD clause on 2026-10-15 meant a
    hand-written UPDATE against the live /root/work/work.db - which bypasses the audit
    trail this tool exists to be. `dod` is exactly the field a shift must be able to
    correct when a DoD turns out to be unmeasurable, so the correction belongs here.

    The previous text is never overwritten silently: every changed field is written to
    the `note` trail as "field: OLD -> NEW" in the SAME transaction as the UPDATE, and
    `show` prints that trail, so what the item used to say survives the correction.

    Exit codes depart from the house `out()` habit on purpose: a REFUSED edit returns 2,
    not 0, because "the correction silently did nothing" is the exact failure this verb
    was filed to end. Success returns 0. `--help` returns 0.
    """
    _edit_from_json(a)
    c = connect(Path(a.db))
    r = c.execute("SELECT * FROM work_item WHERE id=?", (a.item,)).fetchone()
    if not r:
        c.close()
        out("error:no-such-item", id=a.item)
        return 2

    changes = []
    if a.title is not None and a.title != r["title"]:
        changes.append(("title", r["title"], a.title))
    if a.dod is not None and a.dod != r["dod"]:
        changes.append(("dod", r["dod"], a.dod))
    if a.why is not None and a.why != (r["why"] or ""):
        changes.append(("why", r["why"] or "", a.why))
    if getattr(a, "blocked_on", None) is not None and \
            a.blocked_on != (r["blocked_on"] or ""):
        changes.append(("blocked_on", r["blocked_on"] or "", a.blocked_on))
    if getattr(a, "not_before", None) is not None and \
            parse_revisit(a.not_before) != (r["not_before"] or ""):
        changes.append(("not_before", r["not_before"] or "", parse_revisit(a.not_before)))
    if a.priority is not None and int(a.priority) != r["priority"]:
        if not 1 <= int(a.priority) <= 9:
            c.close()
            out("error:bad-priority", priority=a.priority,
                hint="priority is 1 (production outage / customer-facing break) .. 9 (nice-to-have)")
            return 2
        changes.append(("priority", r["priority"], int(a.priority)))

    if not changes:
        c.close()
        out("error:nothing-to-edit", id=a.item,
            hint="pass --title/--dod/--why/--priority/--not-before with a value that "
                 "DIFFERS from the stored one; an edit that changes nothing is not recorded")
        return 2

    t = now()
    body = "; ".join("%s: %s -> %s" % (f, old, new) for f, old, new in changes)
    c.execute("UPDATE work_item SET title=?, dod=?, why=?, priority=?, blocked_on=?, "
              "not_before=?, updated_at=? WHERE id=?",
              (a.title if a.title is not None else r["title"],
               a.dod if a.dod is not None else r["dod"],
               a.why if a.why is not None else r["why"],
               int(a.priority) if a.priority is not None else r["priority"],
               a.blocked_on if getattr(a, "blocked_on", None) is not None else r["blocked_on"],
               (parse_revisit(a.not_before) if getattr(a, "not_before", None) is not None
                else r["not_before"]),
               t, a.item))
    cur = c.execute("INSERT INTO note(at,kind,subject,body) VALUES(?,?,?,?)",
                    (t, "edit", "item:%d" % a.item,
                     "%s  [by %s]" % (body, a.by or whoami())))
    c.commit()
    c.close()
    return out("edit-ok", id=a.item, note=cur.lastrowid,
               fields=[f for f, _o, _n in changes])


def cmd_next(a) -> int:
    c = connect(Path(a.db))
    r = _pick_next(c, a.project)
    if not r:
        return out("nothing-todo", project=a.project or "*")
    if a.json:
        print(json.dumps(dict(r), indent=2))
        return 0
    print("ITEM %d  [%s]  project=%s  priority=%d  age=%s" % (
        r["id"], r["state"], r["project"], r["priority"], r["created_at"]))
    print("  %s" % r["title"])
    if r["why"]:
        print("  why: %s" % r["why"])
    print("  definition of done: %s" % r["dod"])
    if r["owner_row"]:
        print("  owner queue row: #%s" % r["owner_row"])
    return 0


def cmd_claim(a) -> int:
    c = connect(Path(a.db))
    r = c.execute("SELECT * FROM work_item WHERE id=?", (a.item,)).fetchone()
    if not r:
        return out("error:no-such-item", id=a.item)
    if r["state"] == "done":
        return out("already-done", id=a.item)
    dupe = _done_title_dupe(c, a.item)
    if dupe and not getattr(a, "allow_done_dupe", False):
        return out("already-done-title", id=a.item, project=r["project"],
                   done_item=dupe["id"], done_at=dupe["done_at"],
                   hint="this exact title is already closed done by item %d; pass "
                        "--allow-done-dupe only if this is genuinely different work"
                        % dupe["id"])
    if r["state"] == "running" and not lease_expired(r):
        if r["claimed_by"] == a.by:
            return out("already-yours", id=a.item, lease=r["lease_until"])
        return out("held-by-other", id=a.item, by=r["claimed_by"], lease=r["lease_until"])
    until = datetime.fromtimestamp(time.time() + a.lease, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    t = now()
    c.execute("UPDATE work_item SET state='running', claimed_by=?, lease_until=?, updated_at=? WHERE id=?",
              (a.by, until, t, a.item))
    cur = c.execute("INSERT INTO attempt(item,worker,started_at,did) VALUES(?,?,?,'started')",
                    (a.item, a.by, t))
    c.commit()
    return out("claimed", id=a.item, attempt=cur.lastrowid, lease_until=until)


def cmd_attempt(a) -> int:
    """The end-of-shift write. This is what makes the system remember."""
    c = connect(Path(a.db))
    r = c.execute("SELECT * FROM work_item WHERE id=?", (a.item,)).fetchone()
    if not r:
        return out("error:no-such-item", id=a.item)
    t = now()
    if a.proof and not a.result:
        return out("error:proof-without-result",
                   hint="a proving command with no quoted output is not evidence")
    if a.state == "blocked" and not (a.blocked_on and a.blocked_on.strip()):
        return out("error:blocked-without-blocker", id=a.item,
                   hint="blocked MUST name the person or external thing that must act "
                        "(--blocked-on); an untyped block is how work goes invisible")
    att = c.execute("SELECT id FROM attempt WHERE item=? AND worker=? AND ended_at IS NULL "
                    "ORDER BY id DESC LIMIT 1", (a.item, a.by)).fetchone()
    repeat_merged = False   # only the INSERT branch below can set it; the UPDATE branch must not NameError
    if att:
        c.execute("UPDATE attempt SET ended_at=?, did=?, proof=?, result=?, left_over=?, state_after=?, "
                  "exit_code=? WHERE id=?",
                  (t, a.did, a.proof, a.result, a.left, a.state,
                   getattr(a, "exit_code", None), att["id"]))
        attempt_id = att["id"]
    else:
        prev = c.execute(
            "SELECT id, did FROM attempt WHERE item=? AND worker=? AND ended_at IS NOT NULL "
            "ORDER BY id DESC LIMIT 1", (a.item, a.by)).fetchone()
        # ITEM 997: one worker closing one item with the SAME did text twice is one
        # outcome recorded twice, not two pieces of work. Before this, every re-close
        # appended a row, which is how identical re-attempts piled up and made an item
        # look like it had been worked far more than it had.
        repeat_merged = bool(prev and _norm_text(prev["did"])
                             and _norm_text(prev["did"]) == _norm_text(a.did))
        if repeat_merged:
            c.execute("UPDATE attempt SET ended_at=?, did=?, proof=?, result=?, left_over=?, "
                      "state_after=?, exit_code=? WHERE id=?",
                      (t, a.did, a.proof, a.result, a.left, a.state,
                       getattr(a, "exit_code", None), prev["id"]))
            attempt_id = prev["id"]
        else:
            cur = c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,proof,result,left_over,"
                            "state_after,exit_code) VALUES(?,?,?,?,?,?,?,?,?,?)",
                            (a.item, a.by, t, t, a.did, a.proof, a.result, a.left, a.state,
                             getattr(a, "exit_code", None)))
            attempt_id = cur.lastrowid
    # An absent --state means "record only". The item keeps the state it had, and if that state
    # is blocked it keeps its blocker and revisit date too: writing blocked_on=NULL would erase
    # the one thing that explains why the item is waiting.
    state = a.state if a.state else r["state"]
    blocked_on = a.blocked_on if state == "blocked" else None
    if state == "blocked" and not (a.blocked_on or "").strip():
        blocked_on = r["blocked_on"]
    # Item 278: a relative offset ("+7d") is resolved to the absolute stamp it names
    # BEFORE it reaches the column. Stored verbatim it sorted below every ISO date and the
    # block was reported due at every --at date forever; an absolute stamp still passes
    # through byte-for-byte, which the selftest asserts.
    # MEASURED 2026-10-18: with no --revisit supplied this fell back to revisit_default() and
    # OVERWROTE the date already recorded, so every diagnostic note pushed a blocked item a week
    # further from being looked at again. Keep what the row already had; an explicit --revisit wins.
    if state == "blocked":
        revisit_at = (parse_revisit(getattr(a, "revisit", None))
                      or r["revisit_at"]
                      or revisit_default())
    else:
        revisit_at = None
    if state == "done" and not (a.proof and a.result):
        state = "todo"          # a claim of done without evidence is not a done
        note = "downgraded: no proof+result supplied"
    else:
        note = None
    c.execute("UPDATE work_item SET state=?, blocked_on=?, revisit_at=?, "
              "claimed_by=CASE WHEN ?='running' THEN claimed_by ELSE NULL END, "
              "lease_until=CASE WHEN ?='running' THEN lease_until ELSE NULL END, "
              "done_at=CASE WHEN ?='done' THEN ? ELSE done_at END, updated_at=? WHERE id=?",
              (state, blocked_on, revisit_at, state, state, state, t, t, a.item))
    c.commit()
    res = out("attempt-recorded", id=a.item, attempt=attempt_id, state=state,
              exit_code=getattr(a, "exit_code", None))
    if note:
        print("  note: %s" % note)
    if repeat_merged:
        print("  note: identical did text merged into attempt %d (item 997)" % attempt_id)
    return res


def cmd_done(a) -> int:
    a.state = "done"
    a.did = a.did or "completed"
    a.left = a.left or ""
    a.blocked_on = None
    return cmd_attempt(a)


def cmd_list(a) -> int:
    c = connect(Path(a.db))
    where, args = [], []
    if a.project:
        where.append("w.project=?")
        args.append(a.project)
    if a.state:
        where.append("w.state=?")
        args.append(a.state)
    q = ("SELECT w.id,w.project,w.title,w.state,w.priority,w.claimed_by,w.lease_until,w.created_at,"
         "w.owner_row, (SELECT COUNT(*) FROM attempt t WHERE t.item=w.id) AS tries "
         "FROM work_item w " + ("WHERE " + " AND ".join(where) + " " if where else "") +
         "ORDER BY CASE w.state WHEN 'running' THEN 0 WHEN 'blocked' THEN 1 WHEN 'todo' THEN 2 ELSE 3 END, "
         "w.priority ASC, w.created_at ASC LIMIT ?")
    args.append(a.limit)
    rows = c.execute(q, args).fetchall()
    if a.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    if not rows:
        print("no items")
        return 0
    print("%-5s %-20s %-8s %-3s %3s %-22s %s" % ("ID", "PROJECT", "STATE", "P", "try", "HELD BY", "TITLE"))
    for r in rows:
        print("%-5d %-20s %-8s %-3d %3d %-22s %s" % (
            r["id"], r["project"], r["state"], r["priority"], r["tries"],
            (r["claimed_by"] or "")[:22], r["title"][:60]))
    return 0


def cmd_show(a) -> int:
    c = connect(Path(a.db))
    r = c.execute("SELECT * FROM work_item WHERE id=?", (a.item,)).fetchone()
    if not r:
        return out("error:no-such-item", id=a.item)
    atts = c.execute("SELECT * FROM attempt WHERE item=? ORDER BY id", (a.item,)).fetchall()
    # Item 361: the edit trail. `cmd_edit` records what a field USED to say here, so show
    # must print it - an audit trail nobody can read is not an audit trail.
    notes = c.execute("SELECT * FROM note WHERE subject=? ORDER BY id",
                      ("item:%d" % a.item,)).fetchall()
    if a.json:
        d = dict(r)
        d["attempts"] = [dict(x) for x in atts]
        d["notes"] = [dict(x) for x in notes]
        print(json.dumps(d, indent=2))
        return 0
    print("ITEM %d  [%s]" % (r["id"], r["state"]))
    print("  project    %s" % r["project"])
    print("  title      %s" % r["title"])
    if r["why"]:
        print("  why        %s" % r["why"])
    print("  dod        %s" % r["dod"])
    print("  priority   %d   created %s" % (r["priority"], r["created_at"]))
    if r["claimed_by"]:
        print("  held by    %s until %s" % (r["claimed_by"], r["lease_until"]))
    if r["blocked_on"]:
        print("  blocked on %s" % r["blocked_on"])
    if r["revisit_at"]:
        print("  revisit at %s" % r["revisit_at"])
    if r["not_before"]:
        print("  not before %s" % r["not_before"])
    if r["owner_row"]:
        print("  owner row  #%s" % r["owner_row"])
    for x in atts:
        print("  -- attempt %d by %s at %s -> %s" % (x["id"], x["worker"], x["started_at"], x["state_after"]))
        for k in ("did", "proof", "result", "left_over"):
            if x[k]:
                print("       %-8s %s" % (k + ":", x[k]))
    for x in notes:
        print("  -- note %d [%s] at %s" % (x["id"], x["kind"], x["at"]))
        print("       %s" % x["body"])
    return 0


def cmd_history(a) -> int:
    c = connect(Path(a.db))
    args = []
    q = ("SELECT t.*, w.project, w.title FROM attempt t JOIN work_item w ON w.id=t.item ")
    if a.project:
        q += "WHERE w.project=? "
        args.append(a.project)
    q += "ORDER BY t.id DESC LIMIT ?"
    args.append(a.limit)
    rows = c.execute(q, args).fetchall()
    if a.json:
        print(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    for r in rows:
        print("%s  item %-4d %-20s %-9s %s" % (
            (r["ended_at"] or r["started_at"]), r["item"], r["project"],
            (r["state_after"] or "-"), (r["did"] or "")[:60]))
    return 0


def cmd_reap(a) -> int:
    """Return expired leases to todo, and release blocks whose dependency has landed.

    Two different kinds of stranded work are recovered here, both under the one command a
    shift already runs when it finds every item held:
      * a `running` item whose worker died (an expired lease carries no one with it); and
      * a `blocked` item whose ENTIRE declared dependency is a ledger item that is already
        done (item 213 - item 41 sat blocked for 8 days behind item 60). The second is the
        only thing in this tool that moves work OUT of `blocked` on evidence rather than on
        a human reading `due`, and it is deliberately narrow: a block that names an
        owner-queue row or a task is a block on a person or an external system and is left
        alone (see _clearable_item_blocks).
    """
    c = connect(Path(a.db))
    rows = c.execute("SELECT id,claimed_by,lease_until FROM work_item WHERE state='running'").fetchall()
    reaped = []
    closed_attempts = 0
    for r in rows:
        if lease_expired(r):
            c.execute("UPDATE work_item SET state='todo', claimed_by=NULL, lease_until=NULL, updated_at=? "
                      "WHERE id=?", (now(), r["id"]))
            c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,state_after) "
                      "VALUES(?,?,?,?,?,'todo')",
                      (r["id"], "reaper", now(), now(),
                       "lease expired (held by %s until %s); returned to todo" % (r["claimed_by"], r["lease_until"])))
            # CLOSE THE ABANDONED ATTEMPT TOO (added 2026-10-22). MEASURED that day: 48 attempts in
            # 24 h sat with state_after NULL for ever, because the shift that opened them was killed
            # before its close step and this command only recorded its own recovery row. The ledger
            # could not answer "what happened to this attempt" - the exact question the proof metric
            # is built on - and every one of the 61 no-proof rows that left an item in todo was a
            # reaper row. The recovery row stays: the recovery is its own event.
            closed = c.execute(
                "UPDATE attempt SET ended_at=?, state_after='todo', "
                "did = COALESCE(NULLIF(did,''), 'no work recorded') || "
                "' | CLOSED BY THE REAPER: the lease expired (held by ' || ? || ' until ' || ? || "
                "') before the shift closed it' "
                "WHERE item=? AND (ended_at IS NULL OR state_after IS NULL)",
                (now(), r["claimed_by"], r["lease_until"], r["id"]))
            closed_attempts += closed.rowcount
            reaped.append(r["id"])
    requeued = []
    for iid in _clearable_item_blocks(c):
        bo = c.execute("SELECT blocked_on FROM work_item WHERE id=?", (iid,)).fetchone()["blocked_on"]
        t = now()
        c.execute("UPDATE work_item SET state='todo', blocked_on=NULL, revisit_at=NULL, "
                  "claimed_by=NULL, lease_until=NULL, updated_at=? WHERE id=?", (t, iid))
        c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,state_after) "
                  "VALUES(?,?,?,?,?,'todo')",
                  (iid, "reaper", t, t,
                   "declared dependency cleared: %s - released blocked -> todo" % bo))
        requeued.append(iid)
    c.commit()
    return out("reaped", items=reaped, count=len(reaped),
               attempts_closed=closed_attempts,
               requeued=requeued, requeued_count=len(requeued))


def _repeatable_attempts(c, item):
    """Closed attempts that carry an OUTCOME, in id order.

    A row with no `did`, or the claim scaffold did='started', records no outcome: it is
    not a re-attempt and counting it as one would inflate the metric.
    """
    return [x for x in c.execute(
        "SELECT * FROM attempt WHERE item=? AND ended_at IS NOT NULL ORDER BY id",
        (item,)).fetchall()
        if _norm_text(x["did"]) and _norm_text(x["did"]) != "started"]


def _reattempt_rows(c, project=None, top=15):
    """Per item: tries, distinct outcome texts, and identical-did repeats."""
    sql = ("SELECT w.id, w.project, w.title, COUNT(a.id) AS tries "
           "FROM work_item w LEFT JOIN attempt a ON a.item=w.id ")
    params = []
    if project:
        sql += "WHERE w.project=? "
        params.append(project)
    sql += "GROUP BY w.id ORDER BY tries DESC, w.id ASC LIMIT ?"
    params.append(int(top))
    rows = []
    for r in c.execute(sql, params).fetchall():
        outs = _repeatable_attempts(c, r["id"])
        texts = [_norm_text(x["did"]) for x in outs]
        rows.append({"item": r["id"], "project": r["project"],
                     "title": (r["title"] or "")[:90], "tries": r["tries"],
                     "outcomes": len(texts), "distinct_did": len(set(texts)),
                     "identical_did_repeats": len(texts) - len(set(texts))})
    return rows


def cmd_reattempts(a) -> int:
    """THE SCOREBOARD FOR ITEM 997: how much of the top of the ledger is re-work.

    Reports, for the N most-attempted items (default 15): total attempts, attempts whose
    text is a real outcome, distinct outcome texts, and identical-did repeats. It also
    reports live items whose title is already `done` in the same project.
    """
    c = connect(Path(a.db))
    rows = _reattempt_rows(c, getattr(a, "project", None), getattr(a, "top", 15))
    dupes = _done_title_dupes(c, getattr(a, "project", None))
    d = {"top": getattr(a, "top", 15), "items": rows,
         "top_identical_did": sum(r["identical_did_repeats"] for r in rows),
         "done_title_dupes": len(dupes),
         "done_title_dupe_items": [x["id"] for x in dupes]}
    if a.json:
        print(json.dumps(d, indent=2))
        return 0
    print("%-5s %-20s %5s %8s %8s %5s  %s" % (
        "ID", "PROJECT", "tries", "outcomes", "distinct", "dup", "TITLE"))
    for r in rows:
        print("%-5d %-20s %5d %8d %8d %5d  %s" % (
            r["item"], r["project"], r["tries"], r["outcomes"],
            r["distinct_did"], r["identical_did_repeats"], r["title"]))
    print("top-%d identical-did re-attempts: %d" % (d["top"], d["top_identical_did"]))
    print("live items whose title is already done: %d%s" % (
        len(dupes), (" " + ", ".join("#%d" % x["id"] for x in dupes)) if dupes else ""))
    return 0


def cmd_dedupe_attempts(a) -> int:
    """MERGE historical identical-did rows, preserving every removed row in a note.

    This is the only place the tool deletes attempt rows, and it does so only for a
    CLOSED attempt whose normalized did text is byte-for-byte the same as an EARLIER
    closed attempt by the same item. The kept row is the earliest; every removed row is
    archived verbatim into a `note` on the item first, so `show` still answers "what
    happened" and the count is not silently lost. Open attempts are never touched.
    `--apply` is required; without it the command reports what it would merge.
    """
    c = connect(Path(a.db))
    top = getattr(a, "top", 15)
    sql = ("SELECT w.id FROM work_item w LEFT JOIN attempt a ON a.item=w.id ")
    params = []
    if getattr(a, "project", None):
        sql += "WHERE w.project=? "
        params.append(a.project)
    sql += "GROUP BY w.id ORDER BY COUNT(a.id) DESC, w.id ASC LIMIT ?"
    params.append(int(top))
    merged, checked = [], 0
    for (iid,) in c.execute(sql, params).fetchall():
        checked += 1
        groups = {}
        for x in _repeatable_attempts(c, iid):
            groups.setdefault(_norm_text(x["did"]), []).append(x)
        for _norm, xs in groups.items():
            if len(xs) < 2:
                continue
            keep, drop = xs[0], xs[1:]
            entry = {"item": iid, "kept_attempt": keep["id"],
                     "removed_attempts": [x["id"] for x in drop],
                     "count": len(drop)}
            merged.append(entry)
            if not a.apply:
                continue
            body = json.dumps([dict(x) for x in drop], indent=2, sort_keys=True)
            c.execute(
                "INSERT INTO note(at,kind,subject,body) VALUES(?,?,?,?)",
                (now(), "dedupe", "item:%d" % iid,
                 "IDENTICAL RE-ATTEMPTS MERGED (item 997, by %s): kept attempt %d; "
                 "removed %d row(s) with the same did text. Full archived rows:\n%s"
                 % (a.by, keep["id"], len(drop), body)))
            c.execute("DELETE FROM attempt WHERE id IN (%s)"
                      % ",".join("?" * len(drop)), [x["id"] for x in drop])
    if a.apply:
        c.commit()
    if a.json:
        print(json.dumps({"checked_items": checked, "applied": bool(a.apply),
                          "merged": merged}, indent=2))
        return 0
    for m in merged:
        print("item %d: %s %d identical row(s) into attempt %d" % (
            m["item"], "merged" if a.apply else "WOULD MERGE", m["count"],
            m["kept_attempt"]))
    print("%s: %d item(s) checked, %d group(s), %d row(s) %s" % (
        "dedupe-attempts", checked, len(merged),
        sum(m["count"] for m in merged), "merged" if a.apply else "would be merged"))
    return 0


def cmd_claim_next(a) -> int:
    """THE ONE CALL A SHIFT MAKES FIRST: pick the next item AND take it, atomically.

    A woken session cannot do `next` then `claim` safely - between the two calls another
    shift can take the same item, and the losing session has already spent its context on
    the wrong task. Measured shape of the problem: three consecutive lpt-website shifts
    worked the same unmerged fix. So the selection and the claim are one call, and the
    claim is what makes the selection true.

    With `--json` (the shift contract uses it) the output is the full item row, so the
    session has the title, the definition of done, the reason and the attempt history
    pointer without a second round trip.
    """
    # ITEM 430 (2026-10-25): a nonexistent project must NOT answer the same
    # `ok: nothing-todo` as an existing project with no todo work. Measured before
    # this guard: `--project zzz-no-such-project-xyz` and `--project cfo` both
    # printed nothing-todo, differing only by the echoed project name, so a shift
    # whose body named a typo could not tell an empty queue from a wrong project.
    project = getattr(a, "project", None)
    if project:
        try:
            known = [r["id"] for r in connect(Path(a.db)).execute(
                "SELECT id FROM project ORDER BY id").fetchall()]
        except Exception:
            known = []
        # An EMPTY project table is a fresh ledger, not a wrong name: leave that
        # path to the ordinary nothing-todo answer so `init` and throwaway stores
        # keep working.
        if known and project not in known:
            kw = {"project": project, "known_projects": known}
            if getattr(a, "json", False):
                print(json.dumps(dict(kw, ok="no-such-project"), sort_keys=True))
            else:
                out("no-such-project", **kw)
            return 2
    c = connect(Path(a.db))
    # AUTO-RESWEEP (item 996). A project shift's first call is this one, so a block whose
    # external condition a machine can re-measure is re-tested HERE, before selection:
    # otherwise a cleared billing/PR/deploy/service block stays invisible until a human
    # remembers to run something. Project-scoped only - a fleet-wide sweep on every claim
    # would probe every blocked item in the estate - and never with --dispatch-ci (a claim
    # must not spend a CI run). Failures are swallowed: a probe must never block a claim.
    if getattr(a, "project", None):
        import contextlib as _ctx
        import io as _io
        _sw = argparse.Namespace(db=a.db, project=a.project, item=None, dry_run=False,
                                 record_still=False, dispatch_ci=False, json=True)
        with _ctx.redirect_stdout(_io.StringIO()):
            try:
                cmd_resweep(_sw)
            except Exception:
                pass
    r = _pick_next(c, a.project)
    if not r:
        # A shift whose OWN handle still leases the only running item must be told
        # `already-yours`, not `held-by-other`. `cmd_claim` already resolves the same-handle
        # case; claim-next must too, or a woken shift is told to stop/reap while its lease is
        # live and `reap` is a no-op. Measured 2026-09-28 (item 67): the personality-system
        # shift nearly abandoned item 38 that way.
        mine = c.execute(
            "SELECT * FROM work_item w WHERE w.state='running' AND w.claimed_by=?"
            + (" AND w.project=?" if a.project else "")
            + " ORDER BY w.priority ASC, w.created_at ASC LIMIT 1",
            ([a.by] + ([a.project] if a.project else []))).fetchone()
        if mine is not None and not lease_expired(mine):
            kw = {"id": mine["id"], "lease": mine["lease_until"],
                  "project": a.project or "*"}
            if a.json:
                print(json.dumps(dict(kw, ok="already-yours"), sort_keys=True))
                return 0
            return out("already-yours", **kw)
        held = c.execute("SELECT COUNT(*) FROM work_item w WHERE w.state='running'"
                         + (" AND w.project=?" if a.project else ""),
                         ([a.project] if a.project else [])).fetchone()[0]
        if held:
            word, kw = "held-by-other", {"held": held, "project": a.project or "*",
                                         "hint": "every item for this project is leased; try `work.py reap`"}
        else:
            word, kw = "nothing-todo", {"project": a.project or "*"}
        # Do not report nothing-todo (or held-by-other) while silently hiding live work.
        # TWO guards, because a block can be stopped for two different reasons:
        #   - its named owner-queue row or task is already finished (items 201/210), and
        #   - it is simply PAST ITS REVISIT TIME (item 214) with nobody prompted to look.
        # Both warnings must come BEFORE the result word, and `--json` must stay EXACTLY
        # one object, so there the same facts travel as object fields.
        warn, warn_kw = _stale_ref_warning(a.db, getattr(a, "owner_queue_db", None))
        due_warn, due_kw = _due_blocked_warning(a.db)
        warn_kw.update(due_kw)
        # ITEM 997/1445: selection no longer skips on a done title (renewables reuse it),
        # but a live item whose title is already done still must not be quiet: name every
        # such item and the done item that carries its title, in the dict and on the human
        # path. This is now advisory - it never hides claimable work.
        dupes = _done_title_dupes(c, getattr(a, "project", None))
        warn_kw["done_title_dupes"] = dupes
        warn_kw["done_title_dupes_count"] = len(dupes)
        if a.json:
            print(json.dumps(dict(kw, ok=word, **warn_kw), sort_keys=True))
            return 0
        if warn:
            print(warn)
        if dupes:
            print("work.py: %d item(s) not selected because their exact title is already "
                  "done: %s" % (len(dupes), ", ".join(
                      "#%d->#%d" % (d["id"], d["done_item"]) for d in dupes)))
        if due_warn:
            print(due_warn)
        return out(word, **kw)
    # ITEM 1445: claim-next reached this item by SELECTION, so it must be allowed to take
    # it even when the title matches a done row (the renewable case). The dupe is reported
    # in the output below, so the override is visible rather than silent.
    claim = argparse.Namespace(item=r["id"], by=a.by, lease=a.lease, db=a.db,
                               allow_done_dupe=True)
    # `--json` must emit EXACTLY ONE JSON object, so cmd_claim's one-line result word is
    # suppressed here and its meaning is carried by the object's `id`/`lease_until`. Two
    # lines of output broke the shift contract's own parser the first time it ran.
    import contextlib as _ctx
    import io as _io
    _buf = _io.StringIO()
    with _ctx.redirect_stdout(_buf):
        rc = cmd_claim(claim)
    if rc != 0:
        # A refused claim is NOT a claim. Before 1445 this branch printed `ok: claimed`
        # over whatever cmd_claim had refused, so a caller could not tell a claim from a
        # refusal that changed nothing.
        sys.stdout.write(_buf.getvalue())
        return rc
    if a.json:
        row = c.execute("SELECT * FROM work_item WHERE id=?", (r["id"],)).fetchone()
        tries = c.execute("SELECT COUNT(*) FROM attempt WHERE item=?", (r["id"],)).fetchone()[0]
        d = dict(row)
        d["prior_attempts"] = tries
        d["ok"] = "claimed"
        # ITEM 1445: carry the advisory dupe into the machine-readable claim, so the
        # shift can see the title was already done without the claim being blocked.
        dupe = _done_title_dupe(c, r["id"])
        if dupe:
            d["done_title_dupe"] = dict(dupe)
        if tries:
            last = c.execute("SELECT worker,ended_at,did,proof,result,left_over FROM attempt "
                             "WHERE item=? AND ended_at IS NOT NULL ORDER BY id DESC LIMIT 1",
                             (r["id"],)).fetchone()
            d["last_attempt"] = dict(last) if last else None
        # EXACTLY ONE JSON OBJECT, no prefix. A prefix broke the first machine reader of
        # this call by making the output unparseable while looking correct on screen.
        print(json.dumps(d, sort_keys=True))
        return 0
    # cmd_claim's result word was captured so `--json` can emit exactly one object; on the
    # human path it must be re-emitted. Measured 2026-09-28 on the authority: a successful
    # `claim-next` without `--json` wrote 0 bytes to stdout, so a caller could not tell a
    # claim from a no-op.
    sys.stdout.write(_buf.getvalue())
    # ITEM 1445: the human path says the same thing the JSON does - the claim happened,
    # and the title already exists as a done item in this project.
    dupe = _done_title_dupe(c, r["id"])
    if dupe:
        print("work.py: note: title already done as item %d (%s); claimed anyway - "
              "renewable work reuses its title (item 1445)"
              % (dupe["id"], dupe["done_at"]))
    return rc


def _stale_oq_refs(db, owner_queue_db=None):
    """List blocked items whose owner-queue reference is no longer pending.

    THE DEFECT THIS GUARDS (measured 2026-09-30, lpt-sync item 160): _pick_next()
    selects state='todo' only, so once an item is blocked it is invisible to
    claim-next; if the owner_decision_queue row it names is later resolved, the block
    is stale - the item is neither claimable nor actually waiting on the owner, and
    claim-next reports nothing-todo over live work. `lint-refs` exposes the check and
    `claim-next` runs it on the nothing-todo path (item 201) so the silent recurrence
    needs no human to remember the subcommand.

    Returns (stale, blocked_count, refs_checked, error). `error` is a string when the
    owner-queue store could not be read; stale is then empty and the caller must say so
    rather than imply the ledger is clean.
    """
    c = connect(Path(db))
    rows = c.execute("SELECT id, project, owner_row, blocked_on FROM work_item "
                     "WHERE state='blocked' ORDER BY id").fetchall()
    # A ledger item named in blocked_on can hold a block on its own. Read the states in the SAME
    # connection as the rows, so the suppression below cannot filter the row set with a state
    # snapshot that disagrees with it.
    item_states = {r["id"]: r["state"]
                   for r in c.execute("SELECT id, state FROM work_item")}
    oq_path = resolve_oq_db(owner_queue_db)
    try:
        # mode=ro and no schema script: never write, never take a lock, and never even
        # CREATE TABLE against the live production database.
        oq = sqlite3.connect("file:%s?mode=ro" % oq_path, uri=True, timeout=15)
        oq.row_factory = sqlite3.Row
        status = {r["id"]: r["status"]
                  for r in oq.execute("SELECT id, status FROM owner_decision_queue")}
        oq.close()
    except Exception as exc:
        c.close()
        return [], len(rows), 0, "%s: %s" % (type(exc).__name__, exc)

    stale, refs_checked = [], 0
    for r in rows:
        # A DECIDED owner_row is PROVENANCE, not the gate, once blocked_on also declares a LIVE
        # ledger-item dependency (item 433, measured 2026-10-16). Items 184 and 207 both kept
        # owner_row 502 - whose resolution FILED housekeeping item 318 - and quoted the LIVE item
        # 318 / its live predecessor as the thing actually holding them; the block is real, 318 is
        # state todo, and 318's landing is already visible through _stale_item_refs. Reporting the
        # decided row STALE returned still-blocked items to todo and burned a shift (item 386).
        # The dep must EXIST and be non-terminal: a missing id proves nothing (see
        # _stale_item_refs), and a done/dropped dep leaves the owner row as the only gate, which
        # must still be STALE.
        deps = {int(m) for m in _ITEM_ANY_RE.findall(r["blocked_on"] or "")}
        if any(item_states.get(i) is not None and item_states[i] not in _LEDGER_TERMINAL
               for i in deps - {r["id"]}):
            continue
        refs = set()
        if r["owner_row"] is not None:
            refs.add(int(r["owner_row"]))
        if r["blocked_on"]:
            refs.update(int(m) for m in _OQ_REF_RE.findall(r["blocked_on"]))
        for oid in sorted(refs):
            refs_checked += 1
            st = status.get(oid)
            if st == "pending":
                continue
            stale.append({"item": r["id"], "project": r["project"], "owner_queue_id": oid,
                          "owner_queue_status": st if st is not None else "missing",
                          "blocked_on": r["blocked_on"]})
    c.close()
    return stale, len(rows), refs_checked, None



def _orphan_prose_owner_refs(db, owner_queue_db=None):
    """List LIVE items whose title/why names an owner-queue row while owner_row is NULL.

    THE DEFECT THIS GUARDS (measured 2026-10-16, lpt-sync item 386): the 01:18Z
    decided-gate sweep returned item 184 to todo citing an EMPTY owner-row id, because
    work_item.owner_row was NULL while owner-queue 502 was item 184's decision. The sweep
    could not match the item to the row it had just resolved, so it recorded a phantom
    unblock on a still-blocked item and burned a shift.

    A prose mention is a REFERENCE, not a gate, so this attaches nothing: it names the row
    that must be written into owner_row with `work.py owner-row <item> --owner-row <n>`.
    Only a PENDING row can still be an unlinked dependency. A RESOLVED row named in prose is
    provenance (item 433, measured on items 559/1186 on 2026-10-23) and is not reported: the
    old `link it` advice would have made _stale_oq_refs call both items STALE.
    Only LIVE rows are scanned (todo, blocked, running) - a done/dropped item's provenance
    mention can misfire in no sweep. An `owner` ref inside blocked_on is already covered by
    _stale_oq_refs; the attempt/note trail is deliberately NOT scanned, because every
    lpt-sync attempt names owner-queue #502 in prose and that would flood.

    Returns (orphans, live_count).
    """
    c = connect(Path(db))
    rows = c.execute("SELECT id, project, state, owner_row, title, why FROM work_item "
                     "WHERE state IN ('todo','blocked','running') ORDER BY id").fetchall()
    orphans = []
    for r in rows:
        if r["owner_row"] is not None:
            continue
        refs = set()
        for field in ("title", "why"):
            if r[field]:
                # A YEAR IS NOT A ROW ID. MEASURED 2026-10-18: item 522 names "#2026" in prose
                # and lint-refs reported it as an unresolved owner-queue reference every 15
                # minutes, while saying in the same breath that it was "probably a year". An
                # unactionable finding trains the reader to ignore the log, so the year band is
                # excluded here. The queue holds ~554 rows, so a real id cannot collide yet.
                refs.update(
                    i for i in (int(m) for m in _OQ_REF_RE.findall(r[field]))
                    if not (1900 <= i <= 2100)
                )
        for oid in sorted(refs):
            orphans.append({"item": r["id"], "project": r["project"], "state": r["state"],
                            "owner_queue_id": oid})
    # VALIDATE THE ID AGAINST THE OWNER-QUEUE STORE, because a prose mention is not an id.
    # MEASURED 2026-10-18: three of eight orphan suggestions named owner-queue #2026 -- a YEAR
    # scraped out of prose -- while the queue held ~549 rows
    # (`select count(*) from owner_decision_queue where id=2026` -> 0), and each was printed as a
    # copy-pasteable `link it: work.py owner-row <id> --owner-row 2026`. The queue lives in a
    # DIFFERENT database from the ledger this function connects to; `resolve_oq_db()` is the one
    # resolver, and it is what `_stale_oq_refs` above uses. Fails OPEN: if the queue cannot be read
    # every ref is reported as existing, which is the old behaviour.
    try:
        _oq = sqlite3.connect("file:%s?mode=ro" % resolve_oq_db(owner_queue_db),
                              uri=True, timeout=15)
        _qstatus = {r[0]: r[1]
                    for r in _oq.execute("SELECT id, status FROM owner_decision_queue")}
        _oq.close()
    except Exception:                                         # noqa: BLE001
        _qstatus = None
    # A RESOLVED/ANSWERED ROW CANNOT GATE, SO A PROSE MENTION OF ONE IS PROVENANCE.
    # MEASURED 2026-10-23 (item 433, attempt 2448): live items 559 and 1186 were reported as
    # ORPHAN with `link it: owner-row ... --owner-row 547|518`, but both rows are RESOLVED and
    # both items cite them as history (559: the authorisation behind its fixes; 1186: the
    # accepted un-pushable snapshot). Following that advice would have written a decided row
    # into owner_row and made _stale_oq_refs report BOTH items STALE - the same false-positive
    # family this lint exists to remove. Report only a ref that can still act: a PENDING row
    # (a real unlinked dependency) or an id that does not exist (a typo or a year).
    # Fails OPEN when the queue cannot be read: every ref is kept, which is the old behaviour.
    if not _qstatus:
        for _o in orphans:
            _o["exists"] = True
        c.close()
        return orphans, len(rows)
    kept = []
    for _o in orphans:
        _oid = _o["owner_queue_id"]
        if _oid not in _qstatus:
            _o["exists"] = False
            kept.append(_o)
            continue
        _o["exists"] = True
        _o["owner_queue_status"] = _qstatus[_oid]
        if _qstatus[_oid] != "pending":
            continue
        kept.append(_o)
    c.close()
    return kept, len(rows)



def _stale_task_refs(db, secretary_db=None):
    """List blocked items whose engineering-task reference is already terminal.

    THE DEFECT THIS GUARDS (measured 2026-09-30, lpt-sync item 210): the item-193/201
    guard covers owner-queue rows only. An item blocked on a TASK (task 27217 completed
    16:58:01Z while item 86 sat blocked on it) is invisible to claim-next, and once that
    task is done the item is neither claimable nor waiting on anyone - claim-next returns
    a bare nothing-todo over live work while the C06 ERRORs it gated stay unfixed.

    Read-only against the production store. A missing `tasks` table means "this store
    carries no task refs", not an unreadable store, so the tool still runs against a
    ledger-only fixture; any other read failure is reported to the caller.

    Returns (stale, blocked_count, refs_checked, error).
    """
    c = connect(Path(db))
    rows = c.execute("SELECT id, project, blocked_on FROM work_item "
                     "WHERE state='blocked' ORDER BY id").fetchall()
    path = resolve_oq_db(secretary_db)
    try:
        oq = sqlite3.connect("file:%s?mode=ro" % path, uri=True, timeout=15)
        oq.row_factory = sqlite3.Row
        status = {r["id"]: r["status"]
                  for r in oq.execute("SELECT id, status FROM tasks")}
        oq.close()
    except sqlite3.OperationalError as exc:
        c.close()
        if "no such table" in str(exc).lower():
            return [], len(rows), 0, None
        return [], len(rows), 0, "%s: %s" % (type(exc).__name__, exc)
    except Exception as exc:
        c.close()
        return [], len(rows), 0, "%s: %s" % (type(exc).__name__, exc)

    stale, refs_checked = [], 0
    for r in rows:
        if not r["blocked_on"]:
            continue
        for tid in sorted({int(m) for m in _TASK_REF_RE.findall(r["blocked_on"])}):
            refs_checked += 1
            st = status.get(tid)
            if st is not None and st.lower() not in _TASK_TERMINAL:
                continue
            stale.append({"item": r["id"], "project": r["project"], "task_id": tid,
                          "task_status": st if st is not None else "missing",
                          "blocked_on": r["blocked_on"]})
    c.close()
    return stale, len(rows), refs_checked, None


def _stale_item_refs(db):
    """List blocked items whose blocked_on declares a LEDGER-item dependency that is finished.

    THE DEFECT THIS GUARDS (ledger item 213, measured 2026-10-14): item 41 was blocked on
    item 60; item 60 completed 2026-10-14 and item 41 stayed `blocked` with a 2026-10-20
    revisit while claim-next answered nothing-todo - the dialpad -> lpt-hub -> production
    sync chain stalled for 8 days behind a blocker that had already landed.
    _stale_oq_refs and _stale_task_refs cannot see it: a bare "item 54" is deliberately not
    read as an owner-queue row, and it is not a "task N" either, so a dependency named as a
    LEDGER item was re-evaluated by nothing.

    Only a reference whose item EXISTS and is terminal (`done`/`dropped`) is reported. A
    missing id is NOT evidence that a block is clear - free text names history and other
    corpora - and (see _ITEM_DEP_RE) a bare prose "item N" is not a dependency at all.

    Read-only against THIS ledger, so it cannot fail on an unreadable external store.
    Returns (stale, blocked_count, refs_checked, error).
    """
    c = connect(Path(db))
    rows = c.execute("SELECT id, project, blocked_on FROM work_item "
                     "WHERE state='blocked' ORDER BY id").fetchall()
    states = {r["id"]: r["state"] for r in c.execute("SELECT id, state FROM work_item")}
    c.close()
    stale, refs_checked = [], 0
    for r in rows:
        if not r["blocked_on"]:
            continue
        for tid in sorted({int(m) for m in _ITEM_DEP_RE.findall(r["blocked_on"])}):
            refs_checked += 1
            st = states.get(tid)
            if st is None or st not in _LEDGER_TERMINAL:
                continue
            stale.append({"item": r["id"], "project": r["project"], "dep_item": tid,
                          "dep_state": st, "blocked_on": r["blocked_on"]})
    return stale, len(rows), refs_checked, None


def _clearable_item_blocks(c):
    """Blocked items whose ENTIRE declared dependency is a ledger item that is already done.

    This is the RE-QUEUE half of item 213. A block whose dependency has landed is not a
    block any more, and leaving it in `blocked` is how item 41 sat dormant for 8 days. An
    item qualifies only when BOTH hold:
      * blocked_on declares at least one ledger-item dependency (_ITEM_DEP_RE), and EVERY
        ledger item it names exists and is terminal; and
      * blocked_on names NO owner-queue row and NO engineering task at all - those are
        blocks on a PERSON or an external system, and a shift may not clear those for him
        by finishing an unrelated ledger item.

    Returns the list of ids it moved (the caller commits and records the attempt rows).
    """
    rows = c.execute("SELECT id, blocked_on FROM work_item "
                     "WHERE state='blocked' ORDER BY id").fetchall()
    states = {r["id"]: r["state"] for r in c.execute("SELECT id, state FROM work_item")}
    moved = []
    for r in rows:
        bo = r["blocked_on"] or ""
        deps = {int(m) for m in _ITEM_DEP_RE.findall(bo)}
        if not deps:
            continue
        if _OQ_REF_RE.search(bo) or _TASK_REF_RE.search(bo):
            continue
        if any(states.get(d) not in _LEDGER_TERMINAL for d in deps):
            continue
        moved.append(r["id"])
    return moved


def _stale_ref_warning(db, owner_queue_db=None):
    """The claim-next warning payload for stale refs, or (None, {}).

    Covers owner-queue rows (items 193/201), engineering tasks (item 210) AND ledger items
    (item 213): a block whose named ledger dependency is already done is invisible and
    unreleasable too. Human output gets a one-line warning naming the stale item ids;
    `--json` output must stay EXACTLY ONE object, so there the same facts travel as object
    fields.
    """
    oq_stale, _nb1, _r1, oq_err = _stale_oq_refs(db, owner_queue_db)
    tk_stale, _nb2, _r2, tk_err = _stale_task_refs(db, owner_queue_db)
    it_stale, _nb3, _r3, it_err = _stale_item_refs(db)
    errs = [e for e in (oq_err, tk_err, it_err) if e]
    if errs:
        return ("WARNING: stale-reference check could not read the secretary store "
                "(%s); blocked work may be hidden" % "; ".join(errs),
                {"stale_ref_check": "unreadable", "stale_ref_error": "; ".join(errs)})
    if not oq_stale and not tk_stale and not it_stale:
        return None, {}
    kw = {}
    parts = []
    if oq_stale:
        ids = sorted({s["item"] for s in oq_stale})
        parts.append("blocked item(s) %s cite owner-queue rows that are no longer pending"
                     % ",".join(str(i) for i in ids))
        kw["stale_ref_items"] = ids
        kw["stale_refs"] = oq_stale
    if tk_stale:
        ids = sorted({s["item"] for s in tk_stale})
        parts.append("blocked item(s) %s cite engineering tasks that are already done"
                     % ",".join(str(i) for i in ids))
        kw["stale_task_items"] = ids
        kw["stale_task_refs"] = tk_stale
    if it_stale:
        ids = sorted({s["item"] for s in it_stale})
        parts.append("blocked item(s) %s cite ledger items that are already done"
                     % ",".join(str(i) for i in ids))
        kw["stale_item_items"] = ids
        kw["stale_item_refs"] = it_stale
    msg = "WARNING: " + "; ".join(parts) + "; run `work.py lint-refs`"
    kw["stale_ref_warning"] = msg
    return msg, kw


def _due_blocked_warning(db):
    """The claim-next warning for blocked items past their revisit time, or (None, {}).

    THE DEFECT THIS GUARDS (measured 2026-10-07, ledger item 214): `_pick_next` selects
    state='todo' only, so a blocked item is invisible to claim-next; when its revisit time
    passes, nothing and nobody is prompted to look at it, and claim-next reports a bare
    nothing-todo over live work. The stale-ref guard (items 193/201/210) covers only the
    blocks whose named owner-queue row or task is already finished - it cannot see the
    blocks that are simply PAST DUE. The due set was visible only to a shift that
    remembered to run `work.py due`; this makes the same fact part of the one call a
    shift always makes first. Human output names the due item ids BEFORE the result word;
    `--json` must stay EXACTLY ONE object, so the facts travel as object fields.

    A NULL revisit_at is due NOW, exactly as `work.py due` reads it: a block nobody is
    ever prompted to revisit is work disappearing quietly.

    Returns (message, kw) or (None, {}).
    """
    c = connect(Path(db))
    rows = _blocked_due(c)
    c.close()
    if not rows:
        return None, {}
    ids = [r["id"] for r in rows]
    msg = ("WARNING: due blocked item(s) %s are past their revisit time; run `work.py due`"
           % ",".join(str(i) for i in ids))
    return msg, {"due_blocked_items": ids, "due_blocked": [dict(r) for r in rows]}


def cmd_lint_refs(a) -> int:
    """Fail when a blocked item points at an owner-queue row, a task or a ledger item that
    is finished.

    Exit 0 when every reference is live, 1 when at least one is not. A reference to an id
    that does not exist at all is stale too for owner-queue rows and tasks: nothing can ever
    release those, and the store they live in is the authority on whether the id is real. A
    ledger-item ref is the exception (item 213): only an EXISTING ledger item in a terminal
    state is reported, because free text that says "item N" is often prose rather than a
    dependency and a missing id there is not evidence the block is clear.
    """
    stale, nblocked, refs_checked, err = _stale_oq_refs(a.db, a.owner_queue_db)
    if err is not None:
        out("error:owner-queue-unreadable", db=resolve_oq_db(a.owner_queue_db), error=err)
        return 1
    tstale, _nbt, trefs, terr = _stale_task_refs(a.db, a.owner_queue_db)
    if terr is not None:
        out("error:secretary-unreadable", db=resolve_oq_db(a.owner_queue_db), error=terr)
        return 1
    istale, _nbi, irefs, _ierr = _stale_item_refs(a.db)
    orphans, nlive = _orphan_prose_owner_refs(a.db, a.owner_queue_db)
    if a.json:
        print(json.dumps({"stale": stale, "stale_tasks": tstale, "stale_items": istale,
                          "orphan_prose": orphans,
                          "blocked_items": nblocked, "live_items": nlive,
                          "refs_checked": refs_checked, "task_refs_checked": trefs,
                          "item_refs_checked": irefs},
                         sort_keys=True))
    else:
        for s in stale:
            print("STALE item %d (%s) -> owner-queue #%s is %s"
                  % (s["item"], s["project"], s["owner_queue_id"], s["owner_queue_status"]))
        for s in tstale:
            print("STALE item %d (%s) -> task %s is %s"
                  % (s["item"], s["project"], s["task_id"], s["task_status"]))
        for s in istale:
            print("STALE item %d (%s) -> ledger item %s is %s"
                  % (s["item"], s["project"], s["dep_item"], s["dep_state"]))
        for s in orphans:
            if not s.get("exists", True):
                print("UNRESOLVED-REF item %d (%s, %s) -> title/why names owner-queue #%s, which "
                      "does NOT exist in the queue; not a link - probably a year or a task id"
                      % (s["item"], s["project"], s["state"], s["owner_queue_id"]))
                continue
            print("ORPHAN item %d (%s, %s) -> title/why names owner-queue #%s but "
                  "owner_row is NULL; link it: work.py owner-row %d --owner-row %s"
                  % (s["item"], s["project"], s["state"], s["owner_queue_id"],
                     s["item"], s["owner_queue_id"]))
        if stale or tstale or istale or orphans:
            if stale or tstale or istale:
                print("lint-refs: %d stale reference(s) across %d blocked item(s); "
                      "%d owner-queue + %d task + %d ledger item checked"
                      % (len(stale) + len(tstale) + len(istale), nblocked,
                         refs_checked, trefs, irefs))
            print("lint-refs: %d orphan prose reference(s) across %d live item(s) "
                  "- a live item names an owner row in title/why with owner_row NULL"
                  % (len(orphans), nlive))
        else:
            print("lint-refs: clean - %d reference(s) across %d blocked item(s) all "
                  "live, 0 orphan prose ref(s) across %d live item(s)"
                  % (refs_checked, nblocked, nlive))
    return 1 if (stale or tstale or istale or orphans) else 0


def cmd_selftest(a) -> int:
    """Prove the ledger works on a throwaway database. Exit non-zero if it does not."""
    import tempfile
    tmp = Path(tempfile.mkdtemp(prefix="work-selftest-")) / "w.db"
    c = connect(tmp)
    t = now()
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('p','P',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,created_at,updated_at) VALUES('p','i1','cmd',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) VALUES('p','i2','cmd',1,?,?)", (t, t))
    c.commit()
    # selection honours priority
    n = _pick_next(c)
    assert n["title"] == "i2", "priority selection failed: picked %s" % n["title"]
    # a lease held by someone else is refused, and by the same owner is idempotent
    c.execute("UPDATE work_item SET state='running',claimed_by='x',lease_until=? WHERE id=1",
              (datetime.fromtimestamp(time.time() + 600, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),))
    c.commit()
    row = c.execute("SELECT * FROM work_item WHERE id=1").fetchone()
    assert not lease_expired(row), "a live lease read as expired"
    # an expired lease is reapable
    c.execute("UPDATE work_item SET lease_until='2000-01-01T00:00:00Z' WHERE id=1")
    c.commit()
    assert lease_expired(c.execute("SELECT * FROM work_item WHERE id=1").fetchone()), "expired lease not detected"
    c.close()

    # AND THE INVARIANT THAT MATTERS MOST: two shifts must never be handed the same item.
    # The whole point of the ledger is that three consecutive lpt-website shifts worked the
    # same unmerged fix; if selection and claim can disagree, nothing above is worth having.
    db2 = Path(tmp).with_name("w2.db")
    c = connect(db2)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('q','Q',?,?)", (t, t))
    for n in ("a", "b", "c"):
        c.execute("INSERT INTO work_item(project,title,dod,created_at,updated_at) "
                  "VALUES('q',?, 'cmd', ?, ?)", (n, t, t))
    c.commit()
    c.close()
    got = []
    for i in range(3):
        ns = argparse.Namespace(project="q", by="worker%d" % i, lease=600, db=str(db2), json=True)
        ns.item = None
        # cmd_claim_next prints; capture its chosen id by re-reading the ledger instead
        import io as _io
        import contextlib as _ctx
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            cmd_claim_next(ns)
        li = buf.getvalue().strip()
        obj = json.loads(li)
        assert obj.get("ok") == "claimed", "claim-next did not claim: %r" % li
        got.append(obj["id"])
    assert len(set(got)) == 3, "claim-next handed the same item to two workers: %r" % got
    c = connect(db2)
    fourth = argparse.Namespace(project="q", by="worker3", lease=600, db=str(db2), json=True)
    fourth.item = None
    import io as _io
    import contextlib as _ctx
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(fourth)
    c.close()
    assert json.loads(buf.getvalue().strip()).get("ok") == "held-by-other", \
        "an exhausted project must report held-by-other, got %r" % buf.getvalue().strip()
    # AND: the SAME handle that already holds the only running item is told it owns it, not
    # held-by-other. This is item 67 (2026-09-28): claim-next selected only state='todo', so a
    # shift whose own live lease covered the item was instructed to reap - and reap does
    # nothing while the lease is live.
    mine = argparse.Namespace(project="q", by="worker0", lease=600, db=str(db2), json=True)
    mine.item = None
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(mine)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "already-yours", \
        "the same handle that holds the only running item must get already-yours, got %r" \
        % buf.getvalue().strip()
    c = connect(db2)
    owner = c.execute("SELECT id FROM work_item WHERE project='q' AND claimed_by='worker0'").fetchone()
    c.close()
    assert obj.get("id") == owner["id"], \
        "already-yours named item %r, but worker0 holds %r" % (obj.get("id"), owner["id"])
    # AND: a non---json claim-next still prints its result word. The --json path buffers
    # cmd_claim's output so it can emit exactly one object; on the human path that buffer
    # must be flushed, or a successful claim is silent (measured 2026-09-28 on the authority:
    # `claim-next` without --json wrote 0 bytes to stdout on success).
    c = connect(db2)
    c.execute("INSERT INTO work_item(project,title,dod,created_at,updated_at) "
              "VALUES('q','d','cmd',?,?)", (t, t))
    c.commit()
    c.close()
    plain = argparse.Namespace(project="q", by="worker4", lease=600, db=str(db2), json=False)
    plain.item = None
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(plain)
    txt = buf.getvalue().strip()
    assert txt.startswith("claimed"), \
        "non-json claim-next must print its result word, got %r" % txt


    # AND: the owner-queue staleness guard (item 193). A blocked item is invisible to
    # claim-next; if the owner-queue row it names is later resolved, nothing releases it
    # and nothing reports it. cmd_lint_refs must exit non-zero and name every such item,
    # must NOT read a bare ledger ref ("item 54") as an owner-queue row, and must exit 0
    # once every referenced row is pending again.
    oq_db = Path(tmp).with_name("oq.db")
    oc = sqlite3.connect(str(oq_db))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.executemany("INSERT INTO owner_decision_queue(id,status) VALUES(?,?)",
                   [(5, "resolved"), (6, "answered"), (7, "pending"), (998, "resolved")])
    oc.commit()
    oc.close()
    db3 = Path(tmp).with_name("w3.db")
    c = connect(db3)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('r','R',?,?)", (t, t))
    for title, orow, bo, state in (
            ("resolved-owner_row", 5, None, "blocked"),
            ("answered-blocked_on", None, "waiting on owner-queue #6", "blocked"),
            ("pending-is-clean", None, "waiting on owner-queue row 7", "blocked"),
            ("ledger-ref-not-oq", None, "blocked on item 54", "blocked"),
            ("missing-owner_row", 999, None, "blocked"),
            ("todo-is-ignored", 5, None, "todo"),
            ("live-dep-target", None, None, "todo"),
            ("live-dep-is-provenance", 5, "blocked on item 7", "blocked"),
            # (item 1158) The shape shifts actually wrote: "owner decision #N", plus the
            # "owner decision row N" / "owner_decision_queue row N" spellings. Item 9 names
            # a row that is not in the queue at all; item 10 names a RESOLVED row. Both are
            # stale refs the old regex could not see, which is why claim-next hid them.
            ("owner-decision-hash", None, "owner decision #999 (not in the queue)", "blocked"),
            ("owner-decision-row", None, "owner decision row 998 is resolved", "blocked"),
            ("owner-decision-queue", None, "owner_decision_queue row 998 is resolved",
             "blocked")):
        c.execute("INSERT INTO work_item(project,title,dod,state,owner_row,blocked_on,"
                  "created_at,updated_at) VALUES('r',?,'cmd',?,?,?,?,?)",
                  (title, state, orow, bo, t, t))
    c.commit()
    c.close()
    lr = argparse.Namespace(db=str(db3), owner_queue_db=str(oq_db), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr)
    obj = json.loads(buf.getvalue().strip())
    stale = sorted(s["item"] for s in obj["stale"])
    assert rc == 1, "lint-refs must exit 1 on a stale owner-queue ref"
    assert stale == [1, 2, 5, 9, 10, 11], \
        "lint-refs stale set %r, expected [1,2,5,9,10,11]" % stale
    by_id = {s["item"]: s for s in obj["stale"]}
    assert by_id[9]["owner_queue_status"] == "missing", by_id[9]
    assert by_id[10]["owner_queue_status"] == "resolved", by_id[10]
    assert by_id[11]["owner_queue_status"] == "resolved", by_id[11]
    assert "item 54" not in buf.getvalue(), \
        "a bare ledger ref must not be read as an owner-queue row"
    # (item 433) Item 8 carries the SAME decided owner row 5 as item 1, but its blocked_on names
    # LIVE ledger item 7, so the decided row is provenance and must NOT be reported - one fixture
    # proves both directions: item 1 (resolved row, no live dep) stale, item 8 (resolved row, live
    # dep) clean. This is the measured 184/207 shape: decided owner_row 502 + LIVE item 318.
    assert 1 in stale and 8 not in stale, \
        "a decided owner_row is STALE when it is the only gate and PROVENANCE when a LIVE " \
        "ledger item holds the block: stale=%r" % stale
    # AND it is LIVE-ness that suppresses it, not the bare presence of an item ref: once item 7
    # lands (done) the decided owner row is item 8's only gate again and the verdict must return.
    c = connect(db3)
    c.execute("UPDATE work_item SET state='done' WHERE id=7")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 1 and 8 in sorted(s["item"] for s in obj["stale"]), \
        "a decided owner_row must be STALE again once its ledger dep is done: %r" % obj["stale"]
    c = connect(db3)
    c.execute("UPDATE work_item SET state='todo' WHERE id=7")
    c.commit()
    c.close()
    oc = sqlite3.connect(str(oq_db))
    oc.execute("UPDATE owner_decision_queue SET status='pending'")
    oc.execute("INSERT INTO owner_decision_queue(id,status) VALUES(999,'pending')")
    oc.commit()
    oc.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr)
    assert rc == 0, \
        "lint-refs must exit 0 when every ref is pending, got %r" % buf.getvalue().strip()

    # AND: a RESOLVED owner row named in PROSE is provenance, not an unlinked dependency
    # (item 433, measured 2026-10-23 on live items 559 -> #547 and 1186 -> #518, both rows
    # resolved). The old `link it` advice would write the decided row into owner_row and make
    # _stale_oq_refs report the item STALE. A PENDING row named in prose is still an orphan,
    # and an id that does not exist is still reported as unresolved.
    oq_orph = Path(tmp).with_name("oq-orph.db")
    oc = sqlite3.connect(str(oq_orph))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.executemany("INSERT INTO owner_decision_queue(id,status) VALUES(?,?)",
                   [(5, "resolved"), (7, "pending")])
    oc.commit()
    oc.close()
    db_orph = Path(tmp).with_name("w-orph.db")
    c = connect(db_orph)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('o','O',?,?)", (t, t))
    for title, why, orow, state in (
            ("resolved-prose-is-provenance", "deploy authorised by owner decision #5",
             None, "blocked"),
            ("pending-prose-is-orphan", "waiting for owner-queue #7 to answer",
             None, "blocked"),
            ("missing-prose-is-unresolved", "cited owner decision #999 in passing",
             None, "blocked"),
            ("done-item-is-not-scanned", "owner-queue #7", None, "done"),
            ("linked-item-is-not-orphan", "owner-queue #7", 5, "todo")):
        c.execute("INSERT INTO work_item(project,title,why,dod,state,owner_row,"
                  "created_at,updated_at) VALUES('o',?,?,'cmd',?,?,?,?)",
                  (title, why, state, orow, t, t))
    c.commit()
    c.close()
    lo = argparse.Namespace(db=str(db_orph), owner_queue_db=str(oq_orph), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lo)
    obj = json.loads(buf.getvalue().strip())
    assert sorted(o["item"] for o in obj["orphan_prose"]) == [2, 3], \
        "only a pending prose ref and a missing id may be orphans: %r" % obj["orphan_prose"]
    assert {o["item"]: o.get("exists") for o in obj["orphan_prose"]}[3] is False
    assert rc == 1
    # The pending row is decided: its prose mention becomes provenance and stops being an
    # orphan, exactly as it did for 559/547 and 1186/518 on the live ledger.
    oc = sqlite3.connect(str(oq_orph))
    oc.execute("UPDATE owner_decision_queue SET status='resolved' WHERE id=7")
    oc.commit()
    oc.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lo)
    obj = json.loads(buf.getvalue().strip())
    assert sorted(o["item"] for o in obj["orphan_prose"]) == [3], \
        "a resolved prose row must not be an orphan: %r" % obj["orphan_prose"]
    # Only a non-existent id (a typo/year) remains; drop it and the ledger is clean.
    c = connect(db_orph)
    c.execute("UPDATE work_item SET why='annual review #2026' WHERE id=3")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lo)
    assert rc == 0, "lint-refs must exit 0 with no actionable prose ref: %r" % buf.getvalue()
    # AND: claim-next must SURFACE the stale set itself (item 201). Having lint-refs is
    # not enough - the 2026-09-30 silent nothing-todo happened because a human had to
    # remember to run it. A project whose only items are blocked leaves claim-next with
    # nothing to claim: it must name the stale ids before reporting nothing-todo, and must
    # stay silent (and keep --json to exactly one object) once every ref is pending again.
    oc = sqlite3.connect(str(oq_db))
    oc.execute("UPDATE owner_decision_queue SET status='pending'")
    oc.execute("UPDATE owner_decision_queue SET status='resolved' WHERE id=6")
    oc.commit()
    oc.close()
    db4 = Path(tmp).with_name("w4.db")
    c = connect(db4)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('x','X',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,state,blocked_on,revisit_at,"
              "created_at,updated_at) VALUES('x','hidden','cmd','blocked',"
              "'waiting on owner-queue #6','2999-01-01T00:00:00Z',?,?)", (t, t))
    c.commit()
    c.close()
    cn = argparse.Namespace(project="x", by="worker-cn", lease=600, db=str(db4),
                            json=False, owner_queue_db=str(oq_db))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim_next(cn)
    txt = buf.getvalue()
    assert rc == 0, "claim-next must still exit 0 on nothing-todo"
    assert "nothing-todo" in txt, "claim-next lost its nothing-todo word: %r" % txt
    assert "WARNING" in txt, "a resolved ref must warn from claim-next: %r" % txt
    assert txt.index("WARNING") < txt.index("nothing-todo"), \
        "the stale warning must precede the nothing-todo word: %r" % txt
    assert "blocked item(s) 1" in txt, "the warning must name the stale item id: %r" % txt
    cjson = argparse.Namespace(project="x", by="worker-cn2", lease=600, db=str(db4),
                               json=True, owner_queue_db=str(oq_db))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cjson)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "nothing-todo", obj
    assert obj.get("stale_ref_items") == [1], obj
    oc = sqlite3.connect(str(oq_db))
    oc.execute("UPDATE owner_decision_queue SET status='pending'")
    oc.commit()
    oc.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cn)
    txt = buf.getvalue()
    assert "WARNING" not in txt, "an all-pending ledger must not warn: %r" % txt
    assert "nothing-todo" in txt, txt
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cjson)
    obj = json.loads(buf.getvalue().strip())
    assert "stale_ref_items" not in obj, obj
    # AND: an item blocked on an ENGINEERING TASK that is already done is stale too
    # (item 210). The owner-queue guard above cannot see it: task 27217 completed
    # 16:58:01Z while item 86 sat blocked on it and claim-next reported a bare
    # nothing-todo. claim-next must name the task-stale item id and must NOT flag an
    # item whose task is still open, nor read a bare "item 54" as a task.
    tdb = Path(tmp).with_name("tasks.db")
    tc = sqlite3.connect(str(tdb))
    tc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    tc.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    tc.executemany("INSERT INTO tasks(id,status) VALUES(?,?)",
                   [(4242, "done"), (4243, "open")])
    tc.commit()
    tc.close()
    db6 = Path(tmp).with_name("w6.db")
    c = connect(db6)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('y','Y',?,?)", (t, t))
    for title, bo in (("task-done-hidden", "gated by engineering task 4242"),
                      ("task-open-clean", "gated by engineering task 4243"),
                      ("ledger-ref-not-task", "blocked on item 54")):
        c.execute("INSERT INTO work_item(project,title,dod,state,blocked_on,revisit_at,"
                  "created_at,updated_at)"
                  " VALUES('y',?,'cmd','blocked',?,'2999-01-01T00:00:00Z',?,?)", (title, bo, t, t))
    c.commit()
    c.close()
    cn6 = argparse.Namespace(project="y", by="worker-t", lease=600, db=str(db6),
                             json=False, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim_next(cn6)
    txt = buf.getvalue()
    assert rc == 0, txt
    assert "nothing-todo" in txt, txt
    assert "WARNING" in txt, "a done task ref must warn from claim-next: %r" % txt
    assert txt.index("WARNING") < txt.index("nothing-todo"), txt
    assert "blocked item(s) 1" in txt, "must name the task-stale item id: %r" % txt
    assert "blocked item(s) 1,2" not in txt and "blocked item(s) 1,2,3" not in txt, txt
    cj6 = argparse.Namespace(project="y", by="worker-t2", lease=600, db=str(db6),
                             json=True, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cj6)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "nothing-todo", obj
    assert obj.get("stale_task_items") == [1], obj
    assert obj["stale_task_refs"][0]["task_id"] == 4242, obj
    # a live (open) task and a bare ledger ref must not warn
    c = connect(db6)
    c.execute("UPDATE work_item SET blocked_on='gated by engineering task 4243' WHERE id=1")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cn6)
    assert "WARNING" not in buf.getvalue(), buf.getvalue()
    # lint-refs reports the task staleness on its own channel and fails
    lr6 = argparse.Namespace(db=str(db6), owner_queue_db=str(tdb), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr6)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 0, "no stale task after the move, got %r" % buf.getvalue()
    c = connect(db6)
    c.execute("UPDATE work_item SET blocked_on='gated by engineering task 4242' WHERE id=1")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr6)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 1, "a done task ref must fail lint-refs: %r" % buf.getvalue()
    assert [s["item"] for s in obj["stale_tasks"]] == [1], obj
    # AND: item 145 - a block carries a TYPED blocker and a REVISIT time, and `due`
    # prints the ones whose time has passed. Before this, `blocked` was terminal: 11 of
    # 15 open items sat in it and nothing in the system ever moved one out, including
    # four waiting on a merge role that was never scheduled.
    db5 = Path(tmp).with_name("w5.db")
    c = connect(db5)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('x','X',?,?)", (t, t))
    c.execute("INSERT INTO work_item(id,project,title,dod,state,created_at,updated_at) "
              "VALUES(1,'x','a block','cmd','todo',?,?)", (t, t))
    c.commit()
    c.close()
    base = dict(item=1, by="w", did="d", proof="p", result="r", left="", db=str(db5))
    # an untyped block is REFUSED and leaves the item untouched
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_attempt(argparse.Namespace(state="blocked", blocked_on=None, revisit=None, **base))
    assert "error:blocked-without-blocker" in buf.getvalue(), buf.getvalue()
    c = connect(db5)
    assert c.execute("SELECT state FROM work_item WHERE id=1").fetchone()[0] == "todo", \
        "an untyped block must not be written"
    c.close()
    # a typed block is stored with its revisit time, and the invariant holds
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_attempt(argparse.Namespace(state="blocked", blocked_on="owner-queue #1",
                                       revisit="2000-01-01T00:00:00Z", **base))
    c = connect(db5)
    row = c.execute("SELECT blocked_on, revisit_at, state FROM work_item WHERE id=1").fetchone()
    assert row["blocked_on"] == "owner-queue #1", tuple(row)
    assert row["revisit_at"] == "2000-01-01T00:00:00Z", tuple(row)
    assert c.execute("SELECT COUNT(*) FROM work_item WHERE state='blocked' "
                     "AND (blocked_on IS NULL OR revisit_at IS NULL)").fetchone()[0] == 0
    c.close()
    # and the aging source PRINTS it
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at=None))
    txt = buf.getvalue()
    assert "owner-queue #1" in txt, "due must print the overdue block: %r" % txt
    assert "2000-01-01T00:00:00Z" in txt, "due must show the revisit time: %r" % txt
    # a future revisit is NOT due
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at="1999-01-01T00:00:00Z"))
    assert "owner-queue #1" not in buf.getvalue(), \
        "an item whose revisit time has not arrived must not be reported due: %r" % buf.getvalue()
    # Item 278: `--revisit` advertises a RELATIVE offset ("default +7d"), but stored
    # VERBATIM ("+7d") it sorts below every ISO date under SQLite's string ordering, so the
    # block read as due at EVERY --at date. It must be normalized to the absolute stamp it
    # names - anchored on the row, not on the wall clock - and a row that already carries
    # the offset (the live 80/165/184 shape) must read correctly too.
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_attempt(argparse.Namespace(state="blocked", blocked_on="owner-queue #1",
                                       revisit="+7d", **base))
    c = connect(db5)
    rel = c.execute("SELECT revisit_at, updated_at FROM work_item WHERE id=1").fetchone()
    c.close()
    stored, anchor_at = rel["revisit_at"], rel["updated_at"]
    assert stored and "T" in stored and not stored.startswith("+"), \
        "a relative --revisit must be stored as its absolute stamp: %r" % stored
    exp = (datetime.strptime(anchor_at, "%Y-%m-%dT%H:%M:%SZ")
           + timedelta(days=7)).strftime("%Y-%m-%dT%H:%M:%SZ")
    assert stored == exp, "the offset must be anchored on the row: %r != %r" % (stored, exp)
    before = (datetime.strptime(stored, "%Y-%m-%dT%H:%M:%SZ")
              - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    after = (datetime.strptime(stored, "%Y-%m-%dT%H:%M:%SZ")
             + timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at=before))
    assert "owner-queue #1" not in buf.getvalue(), \
        "a +7d block must not be due BEFORE its revisit: %r" % buf.getvalue()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at=after))
    assert "owner-queue #1" in buf.getvalue(), \
        "a +7d block must be due AFTER its revisit: %r" % buf.getvalue()
    c = connect(db5)
    c.execute("UPDATE work_item SET revisit_at='+2d', updated_at='2026-01-01T00:00:00Z' "
              "WHERE id=1")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at="2026-01-02T00:00:00Z"))
    assert "owner-queue #1" not in buf.getvalue(), \
        "a legacy '+2d' must not be due before its anchored revisit: %r" % buf.getvalue()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_due(argparse.Namespace(db=str(db5), json=False, at="2026-01-04T00:00:00Z"))
    assert "owner-queue #1" in buf.getvalue(), \
        "a legacy '+2d' must be due after its anchored revisit: %r" % buf.getvalue()
    # AND: a structured owner-queue ref can be attached to an item that ALREADY EXISTS
    # (item 369). Before this verb the only --owner-row was on `add`, so backfilling a
    # ref onto a live item meant hand-editing sqlite - the path that produced item 363's
    # prose-only ref that _stale_oq_refs could not see. The verb must write owner_row,
    # `show` must print "owner row  #N", and lint-refs must then treat the ref exactly
    # like one filed at add time: clean while pending, STALE once it is resolved.
    oq7 = Path(tmp).with_name("oq7.db")
    oc = sqlite3.connect(str(oq7))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.execute("INSERT INTO owner_decision_queue(id,status) VALUES(42,'pending')")
    oc.commit()
    oc.close()
    db7 = Path(tmp).with_name("w7.db")
    c = connect(db7)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('z','Z',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,state,blocked_on,created_at,updated_at) "
              "VALUES('z','needs-a-ref','cmd','blocked','waiting on the owner',?,?)", (t, t))
    c.commit()
    c.close()
    # the verb exists on the CLI surface, not just as a function
    ns7 = build_parser().parse_args(["owner-row", "1", "--owner-row", "42"])
    assert ns7.func is cmd_owner_row, "owner-row is not wired to cmd_owner_row: %r" % ns7.func
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_owner_row(argparse.Namespace(db=str(db7), item=1, owner_row=42, clear=False))
    txt = buf.getvalue().strip()
    assert rc == 0 and txt.startswith("owner-row-set "), "owner-row did not write: %r" % txt
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_show(argparse.Namespace(db=str(db7), item=1, json=False))
    assert "owner row  #42" in buf.getvalue(), \
        "show must print the attached owner-queue row: %r" % buf.getvalue()
    lr7 = argparse.Namespace(db=str(db7), owner_queue_db=str(oq7), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr7)
    assert rc == 0, "a pending ref attached by the verb must be clean: %r" % buf.getvalue()
    # flip the referenced row off pending: the guard must name item 1 STALE
    oc = sqlite3.connect(str(oq7))
    oc.execute("UPDATE owner_decision_queue SET status='resolved' WHERE id=42")
    oc.commit()
    oc.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lr7)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 1, "a resolved ref attached by the verb must fail lint-refs: %r" % buf.getvalue()
    assert [s["item"] for s in obj["stale"]] == [1], obj
    assert obj["stale"][0]["owner_queue_id"] == 42, obj
    # and --clear removes it again, so a stale/unwanted ref is correctable without raw sqlite
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_owner_row(argparse.Namespace(db=str(db7), item=1, owner_row=None, clear=True))
    assert rc == 0 and "owner-row-set" in buf.getvalue(), buf.getvalue()
    c = connect(db7)
    assert c.execute("SELECT owner_row FROM work_item WHERE id=1").fetchone()[0] is None, \
        "clear must null owner_row"
    c.close()
    # AND: a block that is simply PAST ITS REVISIT TIME must be surfaced by claim-next too
    # (item 214). The stale-ref guards above cover blocks whose named owner-queue row or
    # task is finished; they cannot see the blocks that are merely overdue, and the due set
    # was visible only to a shift that remembered to run `work.py due`. A shift that did
    # not got a bare nothing-todo over live work. claim-next must name the due item ids
    # BEFORE the result word, keep --json to exactly one object, and go quiet - no warning,
    # no extra field - once no block is past its revisit time.
    db8 = Path(tmp).with_name("w8.db")
    c = connect(db8)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('d','D',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,state,blocked_on,revisit_at,"
              "created_at,updated_at) VALUES('d','overdue','cmd','blocked',"
              "'waiting on the owner','2000-01-01T00:00:00Z',?,?)", (t, t))
    c.commit()
    c.close()
    due_cn = argparse.Namespace(project="d", by="worker-due", lease=600, db=str(db8),
                                json=False, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim_next(due_cn)
    txt = buf.getvalue()
    assert rc == 0, "claim-next must still exit 0 on nothing-todo: %r" % txt
    assert "nothing-todo" in txt, txt
    assert "past their revisit time" in txt, \
        "an overdue block must warn from claim-next: %r" % txt
    assert txt.index("WARNING") < txt.index("nothing-todo"), \
        "the due warning must precede the nothing-todo word: %r" % txt
    assert "due blocked item(s) 1" in txt, \
        "the due warning must name the overdue item id: %r" % txt
    due_cj = argparse.Namespace(project="d", by="worker-due2", lease=600, db=str(db8),
                                json=True, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(due_cj)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "nothing-todo", obj
    assert obj.get("due_blocked_items") == [1], obj
    assert obj["due_blocked"][0]["revisit_at"] == "2000-01-01T00:00:00Z", obj
    # a block whose revisit time has NOT arrived is not due: the same ledger goes quiet
    c = connect(db8)
    c.execute("UPDATE work_item SET revisit_at='2999-01-01T00:00:00Z' WHERE id=1")
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(due_cn)
    txt = buf.getvalue()
    assert "WARNING" not in txt, "a block not yet due must not warn: %r" % txt
    assert "nothing-todo" in txt, txt
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(due_cj)
    obj = json.loads(buf.getvalue().strip())
    assert "due_blocked_items" not in obj, obj
    # AND: the owner-queue store is resolved by CONTENT, not by a hard-coded path (item
    # 43, measured 2026-10-13 on the cloud authority). DEFAULT_OQ_DB still names the frozen
    # office-box path, which exists there as an EMPTY copy; lint-refs read it and reported
    # two LIVE owner-queue rows as missing. A store that is readable but holds zero rows
    # must not be trusted to answer "that row is missing" while a live store that DOES hold
    # rows is available.
    empty_oq = Path(tmp).with_name("oq_empty.db")
    oc = sqlite3.connect(str(empty_oq))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.commit()
    oc.close()
    live_oq = Path(tmp).with_name("oq_live.db")
    oc = sqlite3.connect(str(live_oq))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.execute("INSERT INTO owner_decision_queue(id,status) VALUES(7,'pending')")
    oc.commit()
    oc.close()
    db9 = Path(tmp).with_name("w9.db")
    c = connect(db9)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('g','G',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,state,owner_row,created_at,updated_at)"
              " VALUES('g','waiting-on-live-row','cmd','blocked',7,?,?)", (t, t))
    c.commit()
    c.close()
    _g = globals()
    _saved = (_g["DEFAULT_OQ_DB"], _g["_OQ_DB_EXTRA_CANDIDATES"], dict(_g["_OQ_DB_RESOLVED"]))
    try:
        _g["DEFAULT_OQ_DB"] = str(empty_oq)
        _g["_OQ_DB_EXTRA_CANDIDATES"] = (str(live_oq),)
        _g["_OQ_DB_RESOLVED"].clear()
        lr9 = argparse.Namespace(db=str(db9), owner_queue_db=None, json=True)
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            rc = cmd_lint_refs(lr9)
        obj = json.loads(buf.getvalue().strip())
        assert rc == 0 and obj["stale"] == [], \
            "an empty default store must not hide a LIVE row: %r" % buf.getvalue()
        # with no live candidate left, the same empty store must still fail honestly
        _g["_OQ_DB_EXTRA_CANDIDATES"] = ()
        _g["_OQ_DB_RESOLVED"].clear()
        buf = _io.StringIO()
        with _ctx.redirect_stdout(buf):
            rc = cmd_lint_refs(lr9)
        obj = json.loads(buf.getvalue().strip())
        assert rc == 1 and [s["item"] for s in obj["stale"]] == [1], \
            "an empty store with no live candidate must still flag the ref: %r" % buf.getvalue()
    finally:
        _g["DEFAULT_OQ_DB"], _g["_OQ_DB_EXTRA_CANDIDATES"], _cached = _saved
        _g["_OQ_DB_RESOLVED"].clear()
        _g["_OQ_DB_RESOLVED"].update(_cached)
    # AND: a block whose declared dependency is a LEDGER ITEM that is already done must be
    # surfaced by claim-next AND by lint-refs, and RE-QUEUED by reap (item 213). Item 41 sat
    # blocked on item 60 for 8 days after item 60 landed, because _stale_oq_refs and
    # _stale_task_refs deliberately do not read a bare "item N" and so nothing ever
    # re-evaluated the block. TWO traps are guarded here as well: a bare PROSE "item N" is
    # not a dependency and must not be flagged, and a block that ALSO names an owner-queue
    # row is a block on a person - reap must never release it.
    oqA = Path(tmp).with_name("oqA.db")
    oc = sqlite3.connect(str(oqA))
    oc.execute("CREATE TABLE owner_decision_queue (id INTEGER PRIMARY KEY, status TEXT NOT NULL)")
    oc.execute("INSERT INTO owner_decision_queue(id,status) VALUES(7,'pending')")
    oc.commit()
    oc.close()
    dbA = Path(tmp).with_name("wA.db")
    c = connect(dbA)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('a','A',?,?)", (t, t))
    c.execute("INSERT INTO work_item(id,project,title,dod,state,created_at,updated_at) "
              "VALUES(600,'a','the landed dependency','cmd','done',?,?)", (t, t))
    c.execute("INSERT INTO work_item(id,project,title,dod,state,blocked_on,revisit_at,"
              "created_at,updated_at) VALUES(601,'a','the live dependency','cmd','blocked',"
              "'the owner will decide','2999-01-01T00:00:00Z',?,?)", (t, t))
    for iid, title, bo in (
            (1, "dep-on-done", "Prerequisite item 600 must land first"),
            (2, "dep-still-live", "gated by item 601"),
            (3, "prose-not-dep", "so item 3 DoD clause 2 cannot currently be re-proven"),
            (4, "dep-done-plus-owner", "blocked on item 600; owner-queue #7 pending"),
            (5, "dep-missing", "blocked on item 999")):
        c.execute("INSERT INTO work_item(id,project,title,dod,state,blocked_on,revisit_at,"
                  "created_at,updated_at) VALUES(?,'a',?,'cmd','blocked',?,"
                  "'2999-01-01T00:00:00Z',?,?)", (iid, title, bo, t, t))
    c.commit()
    c.close()
    # lint-refs names the cleared-dependency block(s) and only those
    lrA = argparse.Namespace(db=str(dbA), owner_queue_db=str(oqA), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lrA)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 1, "a done ledger dep must fail lint-refs: %r" % buf.getvalue()
    assert sorted(s["item"] for s in obj["stale_items"]) == [1, 4], obj
    assert sorted(s["dep_item"] for s in obj["stale_items"]) == [600, 600], obj
    assert obj["stale"] == [], "no owner-queue ref here is stale: %r" % obj
    # claim-next must SURFACE the same set itself, before its result word
    cnA = argparse.Namespace(project="a", by="worker-lrA", lease=600, db=str(dbA),
                             json=False, owner_queue_db=str(oqA))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim_next(cnA)
    txt = buf.getvalue()
    assert rc == 0 and "nothing-todo" in txt, txt
    assert "blocked item(s) 1,4 cite ledger items that are already done" in txt, \
        "claim-next must name the ledger-stale items: %r" % txt
    assert txt.index("WARNING") < txt.index("nothing-todo"), txt
    assert "prose-not-dep" not in txt, txt
    cjA = argparse.Namespace(project="a", by="worker-lrA2", lease=600, db=str(dbA),
                             json=True, owner_queue_db=str(oqA))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cjA)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "nothing-todo", obj
    assert obj.get("stale_item_items") == [1, 4], obj
    # REAP releases the block whose whole dependency is done, and ONLY that one
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_reap(argparse.Namespace(db=str(dbA), json=True))
    txt = buf.getvalue()
    assert rc == 0 and "requeued" in txt, txt
    assert json.loads(txt.split("reaped", 1)[1])["requeued"] == [1], txt
    c = connect(dbA)
    st = {r["id"]: r["state"] for r in c.execute("SELECT id, state FROM work_item")}
    c.close()
    assert st[1] == "todo", "a cleared block must be re-queued: %r" % st
    assert st[4] == "blocked", "an owner block must NOT be released by reap: %r" % st
    assert st[2] == "blocked" and st[3] == "blocked" and st[5] == "blocked", st
    # and the re-queued item is now genuinely claimable - the chain moves again
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(cjA)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "claimed" and obj.get("id") == 1, obj
    # lint-refs is clean once the released block is gone and the rest are live/prose/missing
    lrA2 = argparse.Namespace(db=str(dbA), owner_queue_db=str(oqA), json=True)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_lint_refs(lrA2)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 1 and sorted(s["item"] for s in obj["stale_items"]) == [4], obj

    # ITEM 361: `edit` corrects a stored field and KEEPS the previous text in the note
    # trail. A tool that can FILE an unmeasurable DoD but not CORRECT it is what forced a
    # hand-written UPDATE against the live ledger on 2026-10-15, bypassing this audit trail.
    edb = Path(tmp).with_name("w3.db")
    c = connect(edb)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('e','E',?,?)", (t, t))
    c.commit()
    c.close()
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_add(argparse.Namespace(db=str(edb), project="e", title="editable",
                                        dod="OLD-DOD-MARKER exits 0", why="w", priority=5,
                                        owner_row=None, source=None, from_json=None,
                                        allow_dupe=False))
    assert rc == 0 and "item-filed" in buf.getvalue(), buf.getvalue()
    eid = json.loads(buf.getvalue().strip().split(" ", 1)[1])["id"]
    _editns = dict(db=str(edb), item=eid, title=None, why=None, priority=None,
                   by="selftest", from_json=None)
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_edit(argparse.Namespace(dod="NEW-DOD-MARKER exits 0", **_editns))
    assert rc == 0 and "edit-ok" in buf.getvalue(), buf.getvalue()
    c = connect(edb)
    stored = c.execute("SELECT dod FROM work_item WHERE id=?", (eid,)).fetchone()["dod"]
    notes = [dict(x) for x in c.execute("SELECT kind, subject, body FROM note").fetchall()]
    c.close()
    assert stored == "NEW-DOD-MARKER exits 0", "edit did not store the new dod: %r" % stored
    assert len(notes) == 1 and notes[0]["kind"] == "edit", notes
    assert notes[0]["subject"] == "item:%d" % eid, notes
    assert "OLD-DOD-MARKER" in notes[0]["body"], \
        "the previous dod must survive in the note trail: %r" % notes[0]["body"]
    # `show` renders BOTH: the new dod on the item, the retired text in the note trail
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_show(argparse.Namespace(db=str(edb), item=eid, json=False))
    txt = buf.getvalue()
    assert rc == 0, txt
    assert "NEW-DOD-MARKER" in txt, txt
    assert "OLD-DOD-MARKER" in txt, "show must print the note trail: %r" % txt
    # an edit that changes NOTHING is refused (rc 2), not silently recorded as an edit
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_edit(argparse.Namespace(dod="NEW-DOD-MARKER exits 0", **_editns))
    assert rc == 2 and "nothing-to-edit" in buf.getvalue(), (rc, buf.getvalue())
    # an unknown item is refused, and writes no note
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_edit(argparse.Namespace(dod="x", item=99999, title=None, why=None,
                                         priority=None, by="selftest", from_json=None,
                                         db=str(edb)))
    assert rc == 2 and "no-such-item" in buf.getvalue(), (rc, buf.getvalue())
    c = connect(edb)
    n = c.execute("SELECT COUNT(*) FROM note").fetchone()[0]
    c.close()
    assert n == 1, "a refused edit must not write a note: %r" % n

    # The DoD for item 361 asks for the literal word PASS; the machine word stays the last
    # line so `... selftest && ...` chains and anything grepping selftest-ok are unaffected.
    c = connect(Path(str(tmp)))   # the earlier block closed its connection
    # ITEM 997: a title already closed done is never handed out again, and the explicit
    # claim refuses it. The duplicate is given priority 0 so ONLY the new exclusion can
    # keep it from being selected.
    c.execute("INSERT INTO work_item(project,title,dod,state,priority,created_at,updated_at,done_at) "
              "VALUES('p','finished work','cmd','done',0,?,?,?)", (t, t, t))
    done_id = c.execute("SELECT id FROM work_item WHERE title='finished work'").fetchone()[0]
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) "
              "VALUES('p','finished work','cmd',0,?,?)", (t, t))
    dupe_id = c.execute("SELECT id FROM work_item WHERE title='finished work' AND state='todo'"
                        ).fetchone()[0]
    assert _done_title_dupe(c, dupe_id)["id"] == done_id, "done-title dupe not detected"
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) "
              "VALUES('p','unique work','cmd',9,?,?)", (t, t))
    c.commit()   # cmd_attempt opens its OWN connection; uncommitted rows are invisible there
    # ITEM 1445: a done-title twin is ADVISORY, not a selection filter. This leftover is
    # priority 0, so if selection still filtered on the done title it would pick 'unique
    # work' instead; it must pick the duplicate, or renewable work starves.
    picked = _pick_next(c)
    assert picked["id"] == dupe_id, \
        "a live todo with a done-title twin must still be SELECTABLE (item 1445): %r" % dict(picked)
    assert any(x["id"] == dupe_id for x in _done_title_dupes(c, "p")), "dupe not reported"

    # ITEM 997: one worker closing one item with identical did text twice records ONE row.
    ns = argparse.Namespace(db=str(tmp), item=dupe_id, by="tester", did="same outcome",
                            proof="cmd", result="ok", left="", state="done",
                            blocked_on=None, revisit=None, exit_code=0,
                            allow_done_dupe=True)
    assert cmd_attempt(ns) == 0
    ns.did = "second outcome"
    assert cmd_attempt(ns) == 0
    assert cmd_attempt(ns) == 0          # identical text: must merge, not append
    n = c.execute("SELECT COUNT(*) FROM attempt WHERE item=? AND did='second outcome'",
                  (dupe_id,)).fetchone()[0]
    assert n == 1, "identical did text appended %d rows instead of merging" % n
    rep_rows = _reattempt_rows(c, "p", 50)
    assert all(r["identical_did_repeats"] == 0 for r in rep_rows), \
        "identical-did repeats still reported: %s" % rep_rows

    # ITEM 1445 DoD: done item A and open todo item B SHARE A TITLE (different ids) and
    # claim-next must return `claimed` B - not nothing-todo, not already-done-title.
    # This is the exact shape roadmap-supply produces: the renewable item re-filed each
    # cycle under the same title. A priority-1 decoy proves selection actually chose B.
    dtdb = Path(tmp).with_name("wdt.db")
    c = connect(dtdb)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('dt','DT',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,state,priority,created_at,updated_at,done_at) "
              "VALUES('dt','renewable work','cmd','done',5,?,?,?)", (t, t, t))
    done_a = c.execute("SELECT id FROM work_item WHERE title='renewable work'").fetchone()["id"]
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) "
              "VALUES('dt','renewable work','cmd',0,?,?)", (t, t))
    open_b = c.execute("SELECT id FROM work_item WHERE title='renewable work' AND state='todo'"
                       ).fetchone()["id"]
    assert done_a != open_b, "fixture must use different ids"
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) "
              "VALUES('dt','decoy work','cmd',1,?,?)", (t, t))
    c.commit()
    c.close()
    # Item 997 stays true for the EXPLICIT verb: a human claim of B still needs the override.
    dtref = argparse.Namespace(item=open_b, by="probe-1445", lease=600, db=str(dtdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim(dtref)
    assert rc == 0 and "already-done-title" in buf.getvalue(), (rc, buf.getvalue())
    # ...but SELECTION must claim B. This is the 1445 defect verbatim.
    dtns = argparse.Namespace(project="dt", by="worker-1445", lease=600, db=str(dtdb),
                              json=True, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        rc = cmd_claim_next(dtns)
    obj = json.loads(buf.getvalue().strip())
    assert rc == 0 and obj.get("ok") == "claimed" and obj.get("id") == open_b, \
        "claim-next must claim the live todo B, not answer nothing-todo/already-done-title: %r" % obj
    assert obj.get("done_title_dupe", {}).get("id") == done_a, \
        "the claimed item must CARRY the advisory done-title warning: %r" % obj
    print("assertion done-title-renewable/claimed ok: done item %d and todo item %d share "
          "a title; claim-next claimed B (id %d) and reported the dupe"
          % (done_a, open_b, open_b))

    # ITEM 1440: a todo item may carry a "not before" UTC stamp, and claim-next must not hand
    # it out while that time is in the future - or refuse it for ever after. Both halves are
    # asserted through cmd_claim_next itself, and each is NAMED in the output so the DoD's
    # "names the two assertions" is satisfied by the command a shift actually runs.
    nbb = Path(tmp).with_name("wnb.db")
    future_nb = (datetime.now(timezone.utc) + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    past_nb = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    c = connect(nbb)
    c.execute("INSERT INTO project(id,title,created_at,updated_at) VALUES('nb','NB',?,?)", (t, t))
    c.execute("INSERT INTO work_item(project,title,dod,priority,not_before,created_at,updated_at) "
              "VALUES('nb','gated-work','cmd',0,?,?,?)", (future_nb, t, t))
    gated_id = c.execute("SELECT id FROM work_item WHERE title='gated-work'").fetchone()[0]
    c.execute("INSERT INTO work_item(project,title,dod,priority,created_at,updated_at) "
              "VALUES('nb','open-work','cmd',9,?,?)", (t, t))
    c.commit()
    c.close()
    # PRIORITY 0 on the gated item: only the gate can keep it from being selected first.
    nb1 = argparse.Namespace(project="nb", by="worker-nb1", lease=600, db=str(nbb),
                             json=True, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(nb1)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "claimed" and obj.get("title") == "open-work", \
        "claim-next must SKIP a todo whose not-before is in the future: %r" % obj
    print("assertion not-before/future-skipped ok: claim-next picked 'open-work' (priority 9), "
          "not the priority-0 item gated to %s" % future_nb)
    c = connect(nbb)
    c.execute("UPDATE work_item SET not_before=? WHERE id=?", (past_nb, gated_id))
    c.commit()
    c.close()
    nb2 = argparse.Namespace(project="nb", by="worker-nb2", lease=600, db=str(nbb),
                             json=True, owner_queue_db=str(tdb))
    buf = _io.StringIO()
    with _ctx.redirect_stdout(buf):
        cmd_claim_next(nb2)
    obj = json.loads(buf.getvalue().strip())
    assert obj.get("ok") == "claimed" and obj.get("id") == gated_id, \
        "claim-next must RETURN the item once its not-before has passed: %r" % obj
    print("assertion not-before/past-returned ok: claim-next picked item %d once its stamp "
          "moved to %s" % (gated_id, past_nb))

    print("PASS")
    return out("selftest-ok", db=str(tmp), exclusive_claims=got)


# ---------------------------------------------------------------- cli


# ---------------------------------------------------------------- resweep (item 996)
# A blocked item is invisible to claim-next. `due --reopen` handles DATE gates and `reap`
# handles ledger-item dependencies, but neither can see a block on an EXTERNAL CONDITION
# that a machine can simply re-measure: CI billing, a merged PR, a deploy, a service. Those
# blocks were only ever re-read by a human remembering to `show` them, so a resolved
# blocker left the item asleep until its revisit date - which is how the four items asleep
# on the GitHub Actions billing block sat untouched after the block had cleared.
#
# The sweep is deliberately conservative. It only tests a block whose own text names one of
# those four machine conditions, it never treats an owner/integrator/approval word as a
# machine condition, and an unreadable probe is `unknown` - never `clear`.

_BILLING_RE = re.compile(
    r"github\s+actions[^\n]{0,160}(billing|spending\s+limit|account\s+payments|"
    r"payments?\s+have\s+failed)"
    r"|(billing|spending\s+limit)[^\n]{0,160}github\s+actions", re.I)
_PR_RE = re.compile(r"\bPR\s*#?\s*(\d{1,6})\b", re.I)
_MERGE_RE = re.compile(r"\b(merg\w*|promot\w*|land\w*|integrat\w*)\b", re.I)
_DEPLOY_RE = re.compile(r"\b(deploy\w*|deployment)\b", re.I)
_UNIT_RE = re.compile(r"\b([a-z0-9][a-z0-9_.@-]{1,80}\.service)\b")
_OWNER_GATE_RE = re.compile(
    r"\b(owner|integrator|confirm\w*|authori[sz]\w*|approval|vendor|customer|"
    r"hardware|person|human)\b", re.I)


def _gh_token():
    """A repo-capable token without ever printing it."""
    tok = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if tok:
        return tok.strip()
    try:
        lines = Path("/root/.git-credentials").read_text().splitlines()
    except OSError:
        return None
    for line in reversed(lines):
        m = re.match(r"https://[^:]+:([^@]+)@", line.strip())
        if m and m.group(1):
            return m.group(1)
    return None


def _gh_api(path, method="GET", body=None, token=None):
    """(status, payload). Never raises; a transport failure is (0, {'message': ...})."""
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        "https://api.github.com" + path, method=method, data=data,
        headers={"Authorization": "Bearer " + (token or ""),
                 "Accept": "application/vnd.github+json",
                 "Content-Type": "application/json",
                 "User-Agent": "work.py-resweep"})
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            raw = resp.read()
            return resp.status, (json.loads(raw) if raw else {})
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            payload = json.loads(raw)
        except Exception:
            payload = {"message": raw[:300].decode("utf-8", "replace")}
        return e.code, payload
    except Exception as e:  # noqa: BLE001 - a probe must never kill the sweep
        return 0, {"message": "%s: %s" % (type(e).__name__, e)}



def _resolve_repo(project, declared):
    """The checkout ON THIS HOST, and its GitHub owner/name slug.

    The project row's repo column is written by whichever host filed it: the lpt-website row
    says `C:\\Users\\ezabz\\Code\\phone-and-tech-full`, which does not exist on the authority
    and made the GitHub probe ask for `/repos/C:\\Users...` (404). Resolve by existence, then
    read the slug from origin - never by guessing from a path string.
    """
    declared = declared or ""
    cands = [declared]
    base = Path(declared.replace("\\", "/")).name if declared else ""
    if project == "lpt-website":
        cands.append("/root/repos/phone-and-tech-full")
    if base:
        cands.append("/root/repos/" + base)
    cands.append("/root/repos/" + project)
    path = next((p for p in cands if p and Path(p).is_dir()), declared)
    slug = None
    try:
        url = subprocess.run(["git", "-C", path, "remote", "get-url", "origin"],
                             capture_output=True, text=True, timeout=20).stdout.strip()
        m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?$", url)
        if m:
            slug = "%s/%s" % (m.group(1), m.group(2))
    except Exception:
        pass
    if not slug and "/" in declared and ":" not in declared and "\\" not in declared:
        slug = declared.strip("/")
    return path, slug


_HOSTED_LABEL_RE = re.compile(r"^(ubuntu|windows|macos)-(latest|\d)", re.I)


def _is_self_hosted_job(job):
    """True when the job was scheduled onto a self-hosted runner.

    MEASURED 2026-10-29 on run 40891663187: the jobs that RAN carry
    labels ['self-hosted','linux','x64','lpt-ci'] and runner_name 'ci-cloud-1'/'ci-cloud-2',
    while every job the billing block refused carries labels ['ubuntu-latest'],
    runner_name='' and steps=[]. A self-hosted job completing says NOTHING about whether
    GitHub-hosted minutes can be scheduled, so it must never be read as that block clearing.
    """
    labels = [str(x).lower() for x in (job.get("labels") or [])]
    if "self-hosted" in labels:
        return True
    runner = (job.get("runner_name") or "").strip()
    if runner and not runner.lower().startswith("github actions"):
        return True
    return False


def _job_started_evidence(job):
    """True only when a GitHub-HOSTED job actually RAN on a runner.

    MEASURED 2026-10-29 (LPT item 846). GitHub creates a job record for a job it refuses to
    schedule for billing with `started_at` set, then fails it seconds later with `steps: []`,
    `runner_name: ""` and the annotation "The job was not started because recent account
    payments have failed...". A probe that reads `started_at` as proof of a start therefore
    reports a live billing block as CLEARED.

    MEASURED again 2026-10-29 15:09Z (LPT item 1393, run 40891663187): the billing block
    refused every GitHub-hosted job (runner='', steps=0) while the SELF-HOSTED ci-cloud-*
    jobs in the same run completed with 9-15 steps. Those self-hosted starts are NOT
    evidence the hosted block cleared - they never needed a hosted minute. Only a hosted
    job with a runner assignment or a step record is proof.
    """
    if _is_self_hosted_job(job):
        return False
    if job.get("runner_name"):
        return True
    return any((s.get("status") == "completed") or s.get("conclusion")
               for s in (job.get("steps") or []))


def _classify_jobs_for_billing(jobs):
    """Classify one run's jobs as clear / blocked / inconclusive for hosted billing.

    'clear'        a GitHub-hosted job got a runner and ran - billing no longer blocks.
    'blocked'      a GitHub-hosted job was REFUSED (runner='', steps=0 below a real
                   conclusion) and no hosted job ran. Self-hosted jobs that ran are named
                   explicitly as NOT hosted proof; that was the 15:09Z false positive.
    'inconclusive' no GitHub-hosted job appears at all (an all-self-hosted workflow), so
                   this run says nothing either way. Never treat it as clear.
    """
    hosted_started, self_hosted_ran, hosted_refused = [], [], []
    for job in jobs or []:
        name = job.get("name") or job.get("id")
        steps_ran = any((s.get("status") == "completed") or s.get("conclusion")
                        for s in (job.get("steps") or []))
        if _is_self_hosted_job(job):
            if steps_ran:
                self_hosted_ran.append((name, job.get("runner_name")))
            continue
        if _job_started_evidence(job):
            hosted_started.append((name, job.get("runner_name"), job.get("started_at")))
        elif (not (job.get("runner_name") or "").strip()
              and job.get("conclusion") not in (None, "skipped")):
            hosted_refused.append(name)

    if hosted_started:
        name, runner, started = hosted_started[0]
        return "clear", ("GitHub-hosted job '%s' RAN on %s at %s (%d hosted job(s) ran) - "
                         "billing no longer blocks scheduling"
                         % (name, runner, started, len(hosted_started)))
    if hosted_refused:
        sh = ", ".join("%s on %s" % (n, r) for n, r in self_hosted_ran[:4])
        hf = ", ".join(str(n) for n in hosted_refused[:6])
        return "blocked", (
            "%d GitHub-hosted job(s) refused with runner='' and steps=0 (%s)%s - billing "
            "still blocks scheduling"
            % (len(hosted_refused), hf,
               ("; self-hosted job(s) that ran are NOT hosted proof: " + sh) if sh else ""))
    return "inconclusive", (
        "no GitHub-hosted job in this run (self-hosted only: %s) - says nothing about "
        "hosted billing" % ", ".join("%s on %s" % (n, r) for n, r in self_hosted_ran[:4]))


def _probe_ci_billing(repo, since, dispatch=False):
    """Re-measure GitHub Actions billing by observing whether a HOSTED job can START.

    Billing/spending-limit failures happen at SCHEDULING time: the run exists, the job never
    starts and carries no steps. GitHub still sets `started_at` on that refused job
    (MEASURED 2026-10-29), so `started_at` is NOT proof of a start. A hosted runner
    assignment or a step record is proof.

    A self-hosted job that runs is also NOT proof (MEASURED 2026-10-29 15:09Z, item 1393):
    self-hosted minutes are not GitHub-hosted minutes, and run 40891663187 showed the
    hosted jobs refused while the ci-cloud-* jobs completed. Only a hosted start clears.
    A 403/rate-limit or no relevant run is `unknown`, never `clear`.

    With dispatch=True and no run to observe, this spends ONE lightweight `ci-rollback`
    dispatch (maintenance.yml, which reports and exits) so the claim is measured live rather
    than inferred from an empty run list.
    """
    token = _gh_token()
    if not token:
        return "unknown", "no GitHub token on the authority (env or /root/.git-credentials)"
    repo = (repo or "").replace("https://github.com/", "").rstrip("/")
    if not repo:
        return "unknown", "no repo checkout or slug to probe"
    if repo.endswith(".git"):
        repo = repo[:-4]

    def runs_since():
        q = "/repos/%s/actions/runs?per_page=30" % repo
        if since:
            q += "&created=%3E%3D" + urllib.parse.quote(since)
        return _gh_api(q, token=token)

    st, data = runs_since()
    if st in (401, 403):
        return "unknown", "GitHub API %s: %s" % (
            st, (data.get("message") or "refused")[:160])
    if st != 200:
        return "unknown", "GitHub API %s: %s" % (
            st, (data.get("message") or "no answer")[:160])

    def survey(runs):
        """(clear_evidence, blocked_details, inconclusive_details) for the first runs."""
        blocked, inconclusive = [], []
        for run in runs[:8]:
            if run.get("status") in ("queued", "in_progress", "requested", "waiting",
                                     "pending"):
                continue
            jst, jobs = _gh_api("/repos/%s/actions/runs/%s/jobs?per_page=100"
                                % (repo, run["id"]), token=token)
            if jst != 200:
                inconclusive.append("run %s: jobs HTTP %s" % (run["id"], jst))
                continue
            verdict, detail = _classify_jobs_for_billing(jobs.get("jobs", []))
            if verdict == "clear":
                return ("%s (run %s <%s>)" % (detail, run.get("id"), run.get("html_url")),
                        blocked, inconclusive)
            if verdict == "blocked":
                blocked.append("run %s: %s" % (run.get("id"), detail))
            else:
                inconclusive.append("run %s: %s" % (run.get("id"), detail))
        return None, blocked, inconclusive

    runs = data.get("workflow_runs", [])
    clear, blocked, inconclusive = survey(runs)
    if clear:
        return "clear", clear
    if blocked:
        return "blocked", ("%d workflow run(s) created on/after %s; %s"
                           % (len(runs), since or "the beginning",
                              " | ".join(blocked[:3])))
    if inconclusive:
        return "unknown", ("no GitHub-hosted job in %d observed run(s) - %s"
                           % (len(runs), " | ".join(inconclusive[:2])))

    if not dispatch:
        return "unknown", ("no workflow run created on/after %s to observe; re-run with "
                           "--dispatch-ci to spend one lightweight run" % (since or "-"))

    # One live dispatch: maintenance.yml task=ci-rollback on the test branch.
    before = time.time()
    st, data = _gh_api("/repos/%s/actions/workflows/maintenance.yml/dispatches" % repo,
                       method="POST", body={"ref": "test",
                                            "inputs": {"task": "ci-rollback"}},
                       token=token)
    if st not in (201, 204):
        return "unknown", ("workflow dispatch refused: HTTP %s %s"
                           % (st, (data.get("message") or "")[:160]))
    deadline = before + 150
    while time.time() < deadline:
        st, data = runs_since()
        if st == 200:
            fresh = [r for r in data.get("workflow_runs", [])
                     if r.get("event") == "workflow_dispatch"
                     and (r.get("created_at") or "") >= since]
            if fresh:
                clear, blocked, _ = survey(fresh)
                if clear:
                    return "clear", "dispatched probe: " + clear
                if fresh[0].get("status") == "completed":
                    r = fresh[0]
                    detail = blocked[0] if blocked else "0 hosted job(s) started"
                    return "blocked", ("dispatched probe run %s <%s> completed %s; %s"
                                       % (r.get("id"), r.get("html_url"),
                                          r.get("conclusion"), detail))
        time.sleep(10)
    return "unknown", ("dispatched probe run on %s but no scheduling result within 150s"
                       % repo)


_GH_PR_CACHE = {}


def _github_repo_slug(repo):
    """'owner/name' for the repo's origin remote, or None."""
    try:
        p = subprocess.run(["git", "-C", repo, "remote", "get-url", "origin"],
                           capture_output=True, text=True, timeout=20)
    except Exception:  # noqa: BLE001
        return None
    url = (p.stdout or "").strip()
    m = re.search(r"github\.com[:/]+([^/]+)/([^/\s]+?)(?:\.git)?$", url)
    return "%s/%s" % (m.group(1), m.group(2)) if m else None


def _github_token():
    for k in ("GITHUB_TOKEN", "GH_TOKEN", "GITHUB_PAT"):
        if os.environ.get(k):
            return os.environ[k]
    try:
        raw = open(os.path.expanduser("~/.git-credentials")).read()
    except Exception:  # noqa: BLE001
        return None
    m = re.search(r"https://[^:]+:([^@]+)@github\.com", raw)
    return m.group(1) if m else None


def _github_pr(repo, pr):
    """GitHub's own record of the PR, or None when it cannot be asked."""
    slug = _github_repo_slug(repo)
    if not slug:
        return None
    key = (slug, pr)
    if key in _GH_PR_CACHE:
        return _GH_PR_CACHE[key]
    tok = _github_token()
    if not tok:
        return None
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/%s/pulls/%d" % (slug, pr),
            headers={"Authorization": "Bearer " + tok,
                     "Accept": "application/vnd.github+json",
                     "User-Agent": "lpt-work-ledger"})
        with urllib.request.urlopen(req, timeout=20) as r:
            d = json.load(r)
        out = {"merged": bool(d.get("merged")), "state": d.get("state"),
               "sha": d.get("merge_commit_sha"),
               "base": (d.get("base") or {}).get("ref")}
    except Exception:  # noqa: BLE001
        return None
    _GH_PR_CACHE[key] = out
    return out


def _on_branch(repo, sha, base):
    if not sha:
        return False
    try:
        p = subprocess.run(["git", "-C", repo, "merge-base", "--is-ancestor", sha, base],
                           capture_output=True, timeout=30)
        return p.returncode == 0
    except Exception:  # noqa: BLE001
        return False


def _probe_merged_pr(repo, pr):
    if not repo:
        return "unknown", "the project has no repo path in the ledger"
    # GitHub first: a revert's commit BODY that names the PR is not a merge, and
    # the old substring grep `(#686)` matched exactly that on 2026-10-26 18:07Z,
    # releasing item 1301 while PR #686 was still open.
    gh = _github_pr(repo, pr)
    try:
        subprocess.run(["git", "-C", repo, "fetch", "--quiet", "origin"],
                       capture_output=True, timeout=90)
    except Exception:  # noqa: BLE001
        pass
    if gh is not None:
        if not gh["merged"]:
            return "blocked", ("GitHub says PR #%d is NOT merged (state=%s, base=%s)"
                               % (pr, gh["state"], gh["base"]))
        for base in ("origin/main", "origin/master"):
            if _on_branch(repo, gh["sha"], base):
                return "clear", ("GitHub says PR #%d merged into %s and %s is on %s"
                                 % (pr, gh["base"], (gh["sha"] or "")[:9], base))
        return "blocked", ("GitHub says PR #%d merged into %s, but its merge commit %s "
                           "is not on origin/main" % (pr, gh["base"], (gh["sha"] or "")[:9]))
    # Fallback when GitHub cannot be asked: only the merge commit's own subject
    # counts. A fixed string cannot be satisfied by a body that mentions or
    # reverts the PR, nor by a nearby number such as (#6869).
    for base in ("origin/main", "origin/master"):
        try:
            p = subprocess.run(
                ["git", "-C", repo, "log", base, "--fixed-strings",
                 "--grep=Merge pull request #%d from " % pr,
                 "--format=%H%x09%s", "-1"],
                capture_output=True, text=True, timeout=60)
        except Exception as e:  # noqa: BLE001
            return "unknown", "git log failed: %s" % e
        line = (p.stdout or "").strip()
        if p.returncode == 0 and line:
            return "clear", "PR #%d is merged: %s %s" % (pr, base, line[:200])
    return "blocked", "no origin/main or origin/master merge commit names PR #%d" % pr


def _probe_deploy(project):
    if project != "lpt-website":
        return "unknown", "deploy probe is wired for lpt-website only"
    try:
        p = subprocess.run(["python3", "/root/bin/lpt-deploy-status.py", "--live"],
                           capture_output=True, text=True, timeout=150)
    except Exception as e:  # noqa: BLE001
        return "unknown", "deploy check did not run: %s" % e
    lines = [l for l in ((p.stdout or "") + "\n" + (p.stderr or "")).splitlines() if l.strip()]
    tail = " | ".join(lines[-3:])[:400]
    if p.returncode == 0 and "MATCH" in (p.stdout or ""):
        return "clear", "deployed bundle MATCHES test head: " + tail
    if p.returncode == 0:
        return "unknown", "deploy check exited 0 without MATCH: " + tail
    return "blocked", "deploy check exit %s: %s" % (p.returncode, tail)


def _probe_service(units):
    states = []
    for u in units:
        try:
            p = subprocess.run(["systemctl", "is-active", u], capture_output=True,
                               text=True, timeout=20)
            s = (p.stdout or p.stderr or "").strip() or "unknown"
        except Exception as e:  # noqa: BLE001
            s = "error:%s" % e
        states.append((u, s))
    bad = [u for u, s in states if s != "active"]
    ev = ", ".join("%s=%s" % (u, s) for u, s in states)
    if bad:
        return "blocked", ev
    return "clear", "all named units active: " + ev


def _classify_block(project, blocked_on):
    """(kind, detail) for a machine-checkable block, else (None, reason)."""
    bo = " ".join((blocked_on or "").split())
    if not bo:
        return None, "no blocked_on text"
    if _BILLING_RE.search(bo):
        return "ci-billing", None
    # A sentence that asks for a PERSON's approval stays a person gate even when
    # it also says "merge PR #686": the merge is then the consequence of the
    # approval, not a machine condition that can clear on its own. Measured
    # 2026-10-26: the owner-approval block on item 1301 was classified
    # merged-pr, probed, and released to todo while the owner had not answered.
    if _OWNER_GATE_RE.search(bo):
        return None, "names a person/approval, not a machine condition"
    m = _PR_RE.search(bo)
    if m and _MERGE_RE.search(bo):
        return "merged-pr", int(m.group(1))
    if _DEPLOY_RE.search(bo):
        return "deploy", None
    units = sorted(set(_UNIT_RE.findall(bo)))
    if units:
        return "service", units
    return None, "no machine-checkable condition named"


def cmd_resweep(a) -> int:
    """Re-test every blocked_on that names a condition a machine can measure.

    Only four kinds are recognised (the DoD for item 996): GitHub Actions billing, a merged
    PR, a deploy, and a service state. A person/approval word in blocked_on is NEVER a
    machine condition. `--dry-run` writes nothing; a `clear` verdict moves the item to
    `todo` and writes the evidence onto an attempt row; `blocked`/`unknown` leave the item
    blocked and leave its revisit date alone.
    """
    c = connect(Path(a.db))
    sql = "SELECT * FROM work_item WHERE state='blocked'"
    params = []
    if getattr(a, "project", None):
        sql += " AND project=?"
        params.append(a.project)
    if getattr(a, "item", None):
        sql += " AND id=?"
        params.append(a.item)
    rows = c.execute(sql + " ORDER BY priority, id", params).fetchall()
    repos = {r["id"]: r["repo"] for r in c.execute("SELECT id, repo FROM project")}
    results, cleared, still, unknown, skipped = [], [], [], [], []
    dispatch_used = False
    t = now()
    for r in rows:
        kind, detail = _classify_block(r["project"], r["blocked_on"])
        if not kind:
            skipped.append({"item": r["id"], "project": r["project"],
                            "reason": detail, "blocked_on": r["blocked_on"]})
            continue
        repo, slug = _resolve_repo(r["project"], repos.get(r["project"]) or "")
        since = (r["updated_at"] or r["created_at"] or "")[:19] + "Z" if r["updated_at"] else None
        if kind == "ci-billing":
            if not slug:
                # Billing is ACCOUNT-wide, not repo-wide. 293/496 name PR 584 in the LPT
                # repo while their project row has no checkout here; probe the account on
                # the repo we can reach rather than answering unknown for want of a path.
                _lp, slug = _resolve_repo("lpt-website", repos.get("lpt-website") or "")
                if slug:
                    slug = "_ACCOUNT_PROBE_REPO:" + slug
            use_dispatch = bool(getattr(a, "dispatch_ci", False)) and not dispatch_used
            probe_slug = slug.split(":", 1)[1] if slug and slug.startswith("_ACCOUNT_PROBE_REPO:") else slug
            verdict, evidence = _probe_ci_billing(probe_slug, since, dispatch=use_dispatch)
            if slug and slug.startswith("_ACCOUNT_PROBE_REPO:"):
                evidence = "account-wide billing measured on %s: %s" % (probe_slug, evidence)
            dispatch_used = dispatch_used or use_dispatch
            cmd = ("see work.py resweep ci-billing probe: GitHub API runs/jobs%s"
                   % (" + one maintenance ci-rollback dispatch" if use_dispatch else ""))
        elif kind == "merged-pr":
            verdict, evidence = _probe_merged_pr(repo, detail)
            cmd = ("git -C %s log origin/main --grep='(#%d)' -1 "
                   "(falls back to origin/master)" % (repo or "<repo>", detail))
        elif kind == "deploy":
            verdict, evidence = _probe_deploy(r["project"])
            cmd = "python3 /root/bin/lpt-deploy-status.py --live"
        else:
            verdict, evidence = _probe_service(detail)
            cmd = "systemctl is-active " + " ".join(detail)
        entry = {"item": r["id"], "project": r["project"], "kind": kind,
                 "verdict": verdict, "evidence": evidence, "proof": cmd,
                 "blocked_on": r["blocked_on"]}
        results.append(entry)
        if verdict == "clear":
            cleared.append(entry)
            if not getattr(a, "dry_run", False):
                c.execute("UPDATE work_item SET state='todo', blocked_on=NULL, "
                          "revisit_at=NULL, claimed_by=NULL, lease_until=NULL, updated_at=? "
                          "WHERE id=? AND state='blocked'", (t, r["id"]))
                c.execute(
                    "INSERT INTO attempt(item,worker,started_at,ended_at,did,proof,result,"
                    "left_over,state_after,exit_code) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], "resweep", t, t,
                     "blocker re-tested and CLEARED (%s); released blocked -> todo" % kind,
                     cmd, evidence, "take the item", "todo", 0))
        elif verdict == "blocked":
            still.append(entry)
            if getattr(a, "record_still", False) and not getattr(a, "dry_run", False):
                c.execute(
                    "INSERT INTO attempt(item,worker,started_at,ended_at,did,proof,result,"
                    "left_over,state_after,exit_code) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (r["id"], "resweep", t, t,
                     "blocker re-tested: STILL BLOCKED (%s)" % kind,
                     cmd, evidence, "re-test on the next sweep", "blocked", 0))
        else:
            unknown.append(entry)
    if not getattr(a, "dry_run", False):
        c.commit()
    c.close()
    if getattr(a, "json", False):
        print(json.dumps({"swept": len(rows), "tested": len(results),
                          "cleared": cleared, "still_blocked": still,
                          "unknown": unknown, "skipped": skipped,
                          "dry_run": bool(getattr(a, "dry_run", False))}, sort_keys=True))
        return 0
    for e in results:
        print("%-9s item %-4d %-14s %s" % (e["verdict"].upper(), e["item"], e["kind"],
                                            e["evidence"]))
    if skipped:
        print("skipped: %s (no machine-checkable condition)"
              % ",".join(str(s["item"]) for s in skipped))
    print("resweep: %d blocked item(s), %d tested, %d cleared, %d still blocked, "
          "%d unknown%s" % (len(rows), len(results), len(cleared), len(still), len(unknown),
                            " [dry-run: nothing written]" if getattr(a, "dry_run", False) else ""))
    return 0


def cmd_due(a) -> int:
    """THE AGING SOURCE: every blocked item whose revisit time has passed.

    Nothing else in this tool ever moves an item OUT of `blocked`: before this, 11 of the
    15 open items sat there and no command, shift or driver was ever prompted to look at
    one again. A block with a named blocker and no revisit time is a decision nobody will
    ever be asked to take, so this is the read that makes `blocked` a state with a
    transition instead of a place work goes to die.
    """
    c = connect(Path(a.db))
    rows = _blocked_due(c, getattr(a, "at", None))

    # --reopen: the transition this command never had. Measured 2026-10-21: 8 blocked items
    # were past their own revisit time and nothing could move any of them out of `blocked`
    # -- `_pick_next` selects `state='todo'` only -- so work that had become available again
    # sat invisible for ever. Two of those eight were provably DATE GATES that had opened
    # (#323 "opens 2026-10-19", #650 "6h sampling window ends 2026-10-19T06:50:05Z").
    #
    # It is deliberately narrow. Only a block whose own `blocked_on` names a DATE GATE, a
    # window, or a scheduled point is reopened; a block naming a person, a vendor, a
    # customer or hardware is left exactly where it is, because reopening those would hand a
    # shift work that is still genuinely blocked and it would re-block it every tick. The
    # reopen writes what it did and why onto the item, and clears revisit_at so the item is
    # not also "due" immediately after being released.
    if getattr(a, "reopen", False):
        import re as _re
        DATE_GATE = _re.compile(
            r"\bdate gate\b|\bopens?\b|\bwindow (ends|opens)\b|\bscheduled\b|"
            r"\buntil \d{4}-\d{2}-\d{2}|\bafter \d{4}-\d{2}-\d{2}", _re.I)
        NOT_A_GATE = _re.compile(
            r"\bno (human|decider)\b|\bowner\b|\bvendor\b|\bcustomer\b|"
            r"\bhardware\b|\bnot checked in\b|\bhas to bring\b|\bbilling\b", _re.I)
        reopened = []
        for r in rows:
            on = " ".join((r["blocked_on"] or "").split())
            if NOT_A_GATE.search(on) or not DATE_GATE.search(on):
                continue
            c.execute(
                "UPDATE work_item SET state='todo', revisit_at=NULL, not_before=NULL, "
                "updated_at=?, blocked_on=? WHERE id=? AND state='blocked'",
                (now(), ("REOPENED 2026-10-21 by `work.py due --reopen`: its own gate had "
                         "passed (" + on[:180] + ")"), r["id"]))
            reopened.append(r["id"])
        c.commit()
        if reopened:
            print("reopened: %s" % ",".join(str(i) for i in reopened))
        else:
            print("reopened: none (no due block names a date gate that has opened)")

    if getattr(a, "json", False):
        print(json.dumps([dict(r) for r in rows], indent=2))
        return 0
    if not rows:
        print("due: no blocked item is past its revisit time")
        return 0
    print("%-5s %-20s %-21s %-3s %s" % ("ID", "PROJECT", "REVISIT-AT", "P", "BLOCKED ON / TITLE"))
    for r in rows:
        print("%-5d %-20s %-21s %-3d %s" % (
            r["id"], r["project"], (r["revisit_at"] or "-never-set-"),
            r["priority"], " ".join((r["blocked_on"] or "").split())[:70]))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="work.py", description=__doc__.split("\n")[1],
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--db", default=str(DEFAULT_DB))
    _from_json_holder = None
    sub = p.add_subparsers(dest="cmd", required=True)

    sub.add_parser("init", help="create the store").set_defaults(func=cmd_init)
    sub.add_parser("selftest", help="prove it works on a throwaway db").set_defaults(func=cmd_selftest)

    pp = sub.add_parser("project").add_subparsers(dest="pcmd", required=True)
    pa = pp.add_parser("add")
    pa.add_argument("--id", required=True)
    pa.add_argument("--title", required=True)
    pa.add_argument("--repo")
    pa.add_argument("--dod")
    pa.add_argument("--note")
    pa.add_argument("--disabled", action="store_true")
    pa.set_defaults(func=cmd_project_add)
    pl = pp.add_parser("list")
    pl.add_argument("--json", action="store_true")
    pl.set_defaults(func=cmd_project_list)

    ad = sub.add_parser("add")
    # --from-json exists because of a MEASURED, REPEATED failure. `--dod` is a shell command with
    # quotes inside it, and passing it through pwsh -> ssh -> base64 -> bash mangled it TWICE on
    # 2026-10-13: item 65's dod arrived as chr(37)||chr(117)||... soup and item 71's did the same.
    # A shift claiming such an item receives an unreadable bar, which is worse than no bar, because it
    # looks like work. `owner-queue.py add --from-json` already solves this the same way and says so in
    # its own help text: "text never passes a shell".  With --from-json, the three required fields come
    # from the file and the flags may be omitted.
    ad.add_argument("--project")
    ad.add_argument("--title")
    ad.add_argument("--dod")
    ad.add_argument("--why")
    ad.add_argument("--priority", type=int)
    ad.add_argument("--owner-row", type=int)
    ad.add_argument("--source")
    ad.add_argument("--not-before", dest="not_before",
                    help="a UTC time (ISO8601 or +3h/+2d) before which claim-next must NOT "
                         "hand this item out; a DoD window that has not opened yet (item 1440)")
    ad.add_argument("--from-json", dest="from_json",
                    help="read project/title/dod/why/priority/owner_row/source from this JSON file, "
                         "or - for stdin. Text never passes a shell.")
    ad.add_argument("--allow-dupe", action="store_true",
                    help="file a second item with the same title even though one is already open")
    ad.set_defaults(func=cmd_add)

    orow = sub.add_parser(
        "owner-row",
        help="attach or clear an owner-queue row ref on an item that already exists")
    orow.add_argument("item", type=int)
    _og = orow.add_mutually_exclusive_group(required=True)
    _og.add_argument("--owner-row", type=int,
                     help="the owner_decision_queue row id this item waits on")
    _og.add_argument("--clear", action="store_true",
                     help="remove the owner-queue reference")
    orow.set_defaults(func=cmd_owner_row)

    ed = sub.add_parser(
        "edit",
        help="correct a stored field (title/dod/why/priority) on an existing item; the "
             "PREVIOUS value is kept in the note trail and printed by `show`. Exits 2 "
             "when it refuses (unknown item, nothing to change, bad priority)")
    ed.add_argument("item", type=int)
    ed.add_argument("--title")
    ed.add_argument("--dod")
    ed.add_argument("--why")
    ed.add_argument("--priority", type=int)
    ed.add_argument("--blocked_on", dest="blocked_on",
                    help="correct the stated blocker on a BLOCKED item; the PREVIOUS value "
                         "is kept in the note trail. A stale block is a CORRECTION, not a "
                         "new decision -- use this instead of closing and refiling.")
    ed.add_argument("--not-before", dest="not_before",
                    help="a UTC time before which claim-next must NOT hand this item out; "
                         "the way to mark a todo whose DoD window has not opened (item 1440)")
    ed.add_argument("--by", default=None, help="who made the correction; recorded in the note trail")
    ed.add_argument("--from-json", dest="from_json",
                    help="read title/dod/why/priority from this JSON file, or - for stdin. "
                         "Text never passes a shell.")
    ed.set_defaults(func=cmd_edit)

    nx = sub.add_parser("next")
    nx.add_argument("--project")
    nx.add_argument("--json", action="store_true")
    nx.set_defaults(func=cmd_next)

    cl = sub.add_parser("claim")
    cl.add_argument("item", type=int)
    cl.add_argument("--by", default=whoami())
    cl.add_argument("--lease", type=int, default=3600)
    cl.add_argument("--allow-done-dupe", action="store_true",
                    help="claim even though this exact title is already closed done in "
                         "the project (item 997; type it on purpose)")
    cl.set_defaults(func=cmd_claim)

    cn = sub.add_parser("claim-next", help="pick the next item and take it in one call")
    cn.add_argument("--project")
    cn.add_argument("--by", required=True,
                    help="a STABLE handle the driver can reap if this session dies")
    cn.add_argument("--lease", type=int, default=3600)
    cn.add_argument("--json", action="store_true")
    cn.add_argument("--owner-queue-db", default=None,
                    help="owner-queue db probed for stale refs (default: %s, or the "
                         "live store when that one is empty)" % DEFAULT_OQ_DB)
    cn.set_defaults(func=cmd_claim_next)

    fin = sub.add_parser("close", help="the end-of-shift write: what you did, the proof, what is left")
    fin.add_argument("item", type=int)
    fin.add_argument("--by", required=True,
                     help="the SAME handle you claimed with")
    fin.add_argument("--did", required=True)
    fin.add_argument("--proof")
    fin.add_argument("--result", dest="result", help="the command's output, quoted")
    fin.add_argument("--left", dest="left")
    fin.add_argument("--state", choices=["todo", "blocked", "done", "dropped"], default="todo")
    fin.add_argument("--blocked-on")
    fin.add_argument("--revisit",
                     help="when an unblocked block must be looked at again (default +7d)")
    fin.add_argument("--exit-code", type=int, default=None,
                     help="the exit code the proving command returned, stored on the "
                          "attempt so the outcome is RECORDED, not derived from its text")
    fin.set_defaults(func=cmd_attempt)

    at = sub.add_parser("attempt")
    at.add_argument("item", type=int)
    at.add_argument("--by", default=whoami())
    at.add_argument("--did")
    at.add_argument("--proof")
    at.add_argument("--result")
    at.add_argument("--left")
    # None = "record only, change nothing". MEASURED 2026-10-18: defaulting to `todo` meant
    # recording a diagnostic note on a blocked item silently unblocked it.
    at.add_argument("--state", choices=["todo", "running", "blocked", "done", "dropped"],
                    default=None)
    at.add_argument("--blocked-on")
    at.add_argument("--revisit",
                    help="when an unblocked block must be looked at again (default +7d)")
    at.add_argument("--exit-code", type=int, default=None,
                    help="the exit code the proving command returned, stored on the attempt")
    at.set_defaults(func=cmd_attempt)

    dn = sub.add_parser("done")
    dn.add_argument("item", type=int)
    dn.add_argument("--by", default=whoami())
    dn.add_argument("--did")
    dn.add_argument("--proof")
    dn.add_argument("--result")
    dn.add_argument("--left")
    dn.add_argument("--exit-code", type=int, default=None,
                    help="the exit code the proving command returned, stored on the attempt")
    dn.set_defaults(func=cmd_done, blocked_on=None)

    ls = sub.add_parser("list")
    ls.add_argument("--project")
    ls.add_argument("--state")
    ls.add_argument("--limit", type=int, default=60)
    ls.add_argument("--json", action="store_true")
    ls.set_defaults(func=cmd_list)

    sh = sub.add_parser("show")
    sh.add_argument("item", type=int)
    sh.add_argument("--json", action="store_true")
    sh.set_defaults(func=cmd_show)

    hi = sub.add_parser("history")
    hi.add_argument("--project")
    hi.add_argument("--limit", type=int, default=40)
    hi.add_argument("--json", action="store_true")
    hi.set_defaults(func=cmd_history)

    rp = sub.add_parser("reap")
    rp.add_argument("--json", action="store_true")
    rp.set_defaults(func=cmd_reap)

    ra = sub.add_parser(
        "reattempts",
        help="report identical-did re-attempts per item and live items whose title is "
             "already done (item 997)")
    ra.add_argument("--project")
    ra.add_argument("--top", type=int, default=15)
    ra.add_argument("--json", action="store_true")
    ra.set_defaults(func=cmd_reattempts)

    dd = sub.add_parser(
        "dedupe-attempts",
        help="merge historical identical-did attempt rows into one, archiving every "
             "removed row in the item's note trail (item 997)")
    dd.add_argument("--project")
    dd.add_argument("--top", type=int, default=15)
    dd.add_argument("--apply", action="store_true")
    dd.add_argument("--by", default=whoami())
    dd.add_argument("--json", action="store_true")
    dd.set_defaults(func=cmd_dedupe_attempts)

    lr = sub.add_parser(
        "lint-refs",
        help="fail if a blocked item references a non-pending owner-queue row, a finished "
             "task or a done ledger item")
    lr.add_argument("--owner-queue-db", default=None,
                    help="owner-queue database (default: %s, or the live store when "
                         "that one is empty)" % DEFAULT_OQ_DB)
    lr.add_argument("--json", action="store_true")
    lr.set_defaults(func=cmd_lint_refs)

    rs = sub.add_parser(
        "resweep",
        help="re-test blocked items whose blocker is machine-checkable (CI billing, merged "
             "PR, deploy, service) and release the ones that have cleared")
    rs.add_argument("--project")
    rs.add_argument("--item", type=int)
    rs.add_argument("--dry-run", action="store_true",
                    help="report verdicts without changing any item")
    rs.add_argument("--record-still", action="store_true",
                    help="also write an attempt row when a probe says STILL BLOCKED")
    rs.add_argument("--dispatch-ci", action="store_true",
                    help="spend one lightweight maintenance ci-rollback dispatch when no "
                         "run exists to observe the billing block")
    rs.add_argument("--json", action="store_true")
    rs.set_defaults(func=cmd_resweep)

    du = sub.add_parser(
        "due",
        help="the aging source: print every blocked item past its revisit time")
    du.add_argument("--at", default=None, help="ISO time to age against (default: now)")
    du.add_argument("--json", action="store_true")
    du.add_argument("--reopen", action="store_true",
                    help="move a due DATE-GATED block back to todo (never a block that "
                         "names a person, vendor, customer or hardware)")
    du.set_defaults(func=cmd_due)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    if getattr(args, "func", None) is not cmd_init and getattr(args, "db", None):
        args.db = resolve_work_db(args.db)
    if getattr(args, "from_json", None) and getattr(args, "func", None) is cmd_add:
        _kwargs_from_json(args)   # CALL_KWARGS_FROM_JSON
    try:
        return args.func(args)
    except Exception as exc:
        print("error:%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
