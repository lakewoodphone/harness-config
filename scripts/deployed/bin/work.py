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
import sys
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

# A reference to an owner-queue row inside the free-text blocked_on. It matches the shapes
# shifts actually write - "owner-queue #206", "owner-queue row #214", "owner-queue row 209",
# "owner_row 5" - and deliberately does NOT match a bare "item 54" or "task 27217": those are
# ledger/engineering references, and reading them as owner-queue rows is the false positive
# that would make this guard useless.
_OQ_REF_RE = re.compile(
    r"(?:owner[\s_-]*queue\s*(?:row\s*)?|owner[\s_-]*row\s*)#?\s*(\d+)", re.I)

# A reference to an engineering TASK (the production store's `tasks` table) inside
# blocked_on. It matches the shapes shifts write - "task 27217", "engineering task 27217",
# "task #27233" - and deliberately does NOT match an owner-queue ref or a bare "item 54".
_TASK_REF_RE = re.compile(r"(?:engineering\s+)?task\s*#?\s*(\d+)", re.I)

# A task in one of these states can never release a block: it is finished or abandoned.
# open/in_progress/in-progress/blocked/pending/paused are live states and do NOT warn.
_TASK_TERMINAL = {"done", "completed", "closed", "cancelled", "canceled"}


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


def _blocked_due(c: sqlite3.Connection, at: str | None = None):
    """Every blocked item whose revisit time has passed (or was never set).

    A NULL revisit_at has no future time at which it becomes due, so it is treated as
    due NOW: a block nobody is ever prompted to revisit is work disappearing quietly,
    which is the failure mode item 145 exists to end.
    """
    at = at or now()
    return c.execute(
        "SELECT id, project, title, priority, blocked_on, revisit_at, updated_at "
        "FROM work_item WHERE state='blocked' "
        "AND (revisit_at IS NULL OR revisit_at <= ?) "
        "ORDER BY (revisit_at IS NULL) DESC, priority ASC, revisit_at ASC", (at,)).fetchall()


def out(word: str, **kw) -> int:
    """One machine-readable result word per call. Never raises."""
    if kw:
        print(word + " " + json.dumps(kw, sort_keys=True))
    else:
        print(word)
    return 0


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


def cmd_add(a) -> int:
    c = connect(Path(a.db))
    proj = c.execute("SELECT id FROM project WHERE id=?", (a.project,)).fetchone()
    if not proj:
        return out("error:unknown-project", project=a.project,
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
    cur = c.execute(
        "INSERT INTO work_item(project,title,why,dod,state,priority,owner_row,created_at,updated_at,source) "
        "VALUES(?,?,?,?,'todo',?,?,?,?,?)",
        (a.project, a.title, a.why, a.dod, int(a.priority), a.owner_row, t, t, a.source))
    c.commit()
    return out("item-filed", id=cur.lastrowid, project=a.project, priority=int(a.priority))


def _pick_next(c, project=None):
    """The selection rule, stated so it can be argued with.
    Priority first (1 is most urgent). Then strict fairness: the project whose OLDEST
    todo item is oldest goes first, so no project starves behind a busy one. Then the
    item's own age. A `running` item whose lease has expired is treated as todo - a
    worker that died must not take its item with it."""
    where = ["w.state='todo'"]
    args = []
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
    if att:
        c.execute("UPDATE attempt SET ended_at=?, did=?, proof=?, result=?, left_over=?, state_after=?, "
                  "exit_code=? WHERE id=?",
                  (t, a.did, a.proof, a.result, a.left, a.state,
                   getattr(a, "exit_code", None), att["id"]))
        attempt_id = att["id"]
    else:
        cur = c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,proof,result,left_over,"
                        "state_after,exit_code) VALUES(?,?,?,?,?,?,?,?,?,?)",
                        (a.item, a.by, t, t, a.did, a.proof, a.result, a.left, a.state,
                         getattr(a, "exit_code", None)))
        attempt_id = cur.lastrowid
    state = a.state
    blocked_on = a.blocked_on if state == "blocked" else None
    revisit_at = ((getattr(a, "revisit", None) or revisit_default())
                  if state == "blocked" else None)
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
    if a.json:
        d = dict(r)
        d["attempts"] = [dict(x) for x in atts]
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
    if r["owner_row"]:
        print("  owner row  #%s" % r["owner_row"])
    for x in atts:
        print("  -- attempt %d by %s at %s -> %s" % (x["id"], x["worker"], x["started_at"], x["state_after"]))
        for k in ("did", "proof", "result", "left_over"):
            if x[k]:
                print("       %-8s %s" % (k + ":", x[k]))
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
    """Return expired leases to todo and record it. A dead worker must not strand work."""
    c = connect(Path(a.db))
    rows = c.execute("SELECT id,claimed_by,lease_until FROM work_item WHERE state='running'").fetchall()
    reaped = []
    for r in rows:
        if lease_expired(r):
            c.execute("UPDATE work_item SET state='todo', claimed_by=NULL, lease_until=NULL, updated_at=? "
                      "WHERE id=?", (now(), r["id"]))
            c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,state_after) "
                      "VALUES(?,?,?,?,?,'todo')",
                      (r["id"], "reaper", now(), now(),
                       "lease expired (held by %s until %s); returned to todo" % (r["claimed_by"], r["lease_until"])))
            reaped.append(r["id"])
    c.commit()
    return out("reaped", items=reaped, count=len(reaped))


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
    c = connect(Path(a.db))
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
        if a.json:
            print(json.dumps(dict(kw, ok=word, **warn_kw), sort_keys=True))
            return 0
        if warn:
            print(warn)
        if due_warn:
            print(due_warn)
        return out(word, **kw)
    claim = argparse.Namespace(item=r["id"], by=a.by, lease=a.lease, db=a.db)
    # `--json` must emit EXACTLY ONE JSON object, so cmd_claim's one-line result word is
    # suppressed here and its meaning is carried by the object's `id`/`lease_until`. Two
    # lines of output broke the shift contract's own parser the first time it ran.
    import contextlib as _ctx
    import io as _io
    _buf = _io.StringIO()
    with _ctx.redirect_stdout(_buf):
        rc = cmd_claim(claim)
    if a.json:
        row = c.execute("SELECT * FROM work_item WHERE id=?", (r["id"],)).fetchone()
        tries = c.execute("SELECT COUNT(*) FROM attempt WHERE item=?", (r["id"],)).fetchone()[0]
        d = dict(row)
        d["prior_attempts"] = tries
        d["ok"] = "claimed"
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


def _stale_ref_warning(db, owner_queue_db=None):
    """The claim-next warning payload for stale refs, or (None, {}).

    Covers BOTH owner-queue rows (items 193/201) and engineering tasks (item 210): a
    block whose named task is already done is invisible and unreleasable too. Human
    output gets a one-line warning naming the stale item ids; `--json` output must stay
    EXACTLY ONE object, so there the same facts travel as object fields.
    """
    oq_stale, _nb1, _r1, oq_err = _stale_oq_refs(db, owner_queue_db)
    tk_stale, _nb2, _r2, tk_err = _stale_task_refs(db, owner_queue_db)
    errs = [e for e in (oq_err, tk_err) if e]
    if errs:
        return ("WARNING: stale-reference check could not read the secretary store "
                "(%s); blocked work may be hidden" % "; ".join(errs),
                {"stale_ref_check": "unreadable", "stale_ref_error": "; ".join(errs)})
    if not oq_stale and not tk_stale:
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
    """Fail when a blocked item points at an owner-queue row or task that is finished.

    Exit 0 when every reference is live, 1 when at least one is not. A reference to an id
    that does not exist at all is stale too: nothing can ever release it.
    """
    stale, nblocked, refs_checked, err = _stale_oq_refs(a.db, a.owner_queue_db)
    if err is not None:
        out("error:owner-queue-unreadable", db=resolve_oq_db(a.owner_queue_db), error=err)
        return 1
    tstale, _nbt, trefs, terr = _stale_task_refs(a.db, a.owner_queue_db)
    if terr is not None:
        out("error:secretary-unreadable", db=resolve_oq_db(a.owner_queue_db), error=terr)
        return 1
    if a.json:
        print(json.dumps({"stale": stale, "stale_tasks": tstale, "blocked_items": nblocked,
                          "refs_checked": refs_checked, "task_refs_checked": trefs},
                         sort_keys=True))
    else:
        for s in stale:
            print("STALE item %d (%s) -> owner-queue #%s is %s"
                  % (s["item"], s["project"], s["owner_queue_id"], s["owner_queue_status"]))
        for s in tstale:
            print("STALE item %d (%s) -> task %s is %s"
                  % (s["item"], s["project"], s["task_id"], s["task_status"]))
        if stale or tstale:
            print("lint-refs: %d stale reference(s) across %d blocked item(s); "
                  "%d owner-queue + %d task checked"
                  % (len(stale) + len(tstale), nblocked, refs_checked, trefs))
        else:
            print("lint-refs: clean - %d reference(s) across %d blocked item(s) all live"
                  % (refs_checked, nblocked))
    return 1 if (stale or tstale) else 0


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
                   [(5, "resolved"), (6, "answered"), (7, "pending")])
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
            ("todo-is-ignored", 5, None, "todo")):
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
    assert stale == [1, 2, 5], "lint-refs stale set %r, expected [1,2,5]" % stale
    assert "item 54" not in buf.getvalue(), \
        "a bare ledger ref must not be read as an owner-queue row"
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
    return out("selftest-ok", db=str(tmp), exclusive_claims=got)


# ---------------------------------------------------------------- cli

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
    ad.add_argument("--project", required=True)
    ad.add_argument("--title", required=True)
    ad.add_argument("--dod", required=True)
    ad.add_argument("--why")
    ad.add_argument("--priority", type=int, default=5)
    ad.add_argument("--owner-row", type=int)
    ad.add_argument("--source")
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

    nx = sub.add_parser("next")
    nx.add_argument("--project")
    nx.add_argument("--json", action="store_true")
    nx.set_defaults(func=cmd_next)

    cl = sub.add_parser("claim")
    cl.add_argument("item", type=int)
    cl.add_argument("--by", default=whoami())
    cl.add_argument("--lease", type=int, default=3600)
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
    at.add_argument("--state", choices=["todo", "running", "blocked", "done", "dropped"], default="todo")
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

    lr = sub.add_parser(
        "lint-refs",
        help="fail if a blocked item references a non-pending owner-queue row")
    lr.add_argument("--owner-queue-db", default=None,
                    help="owner-queue database (default: %s, or the live store when "
                         "that one is empty)" % DEFAULT_OQ_DB)
    lr.add_argument("--json", action="store_true")
    lr.set_defaults(func=cmd_lint_refs)

    du = sub.add_parser(
        "due",
        help="the aging source: print every blocked item past its revisit time")
    du.add_argument("--at", default=None, help="ISO time to age against (default: now)")
    du.add_argument("--json", action="store_true")
    du.set_defaults(func=cmd_due)
    return p


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except Exception as exc:
        print("error:%s: %s" % (type(exc).__name__, exc))
        traceback.print_exc(file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
