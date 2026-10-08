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
import socket
import sqlite3
import sys
import time
import traceback
from datetime import datetime, timezone
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
    state_after TEXT
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
    return c


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
    att = c.execute("SELECT id FROM attempt WHERE item=? AND worker=? AND ended_at IS NULL "
                    "ORDER BY id DESC LIMIT 1", (a.item, a.by)).fetchone()
    if att:
        c.execute("UPDATE attempt SET ended_at=?, did=?, proof=?, result=?, left_over=?, state_after=? "
                  "WHERE id=?",
                  (t, a.did, a.proof, a.result, a.left, a.state, att["id"]))
        attempt_id = att["id"]
    else:
        cur = c.execute("INSERT INTO attempt(item,worker,started_at,ended_at,did,proof,result,left_over,state_after) "
                        "VALUES(?,?,?,?,?,?,?,?,?)",
                        (a.item, a.by, t, t, a.did, a.proof, a.result, a.left, a.state))
        attempt_id = cur.lastrowid
    state = a.state
    blocked_on = a.blocked_on if state == "blocked" else None
    if state == "done" and not (a.proof and a.result):
        state = "todo"          # a claim of done without evidence is not a done
        note = "downgraded: no proof+result supplied"
    else:
        note = None
    c.execute("UPDATE work_item SET state=?, blocked_on=?, claimed_by=CASE WHEN ?='running' THEN claimed_by ELSE NULL END, "
              "lease_until=CASE WHEN ?='running' THEN lease_until ELSE NULL END, "
              "done_at=CASE WHEN ?='done' THEN ? ELSE done_at END, updated_at=? WHERE id=?",
              (state, blocked_on, state, state, state, t, t, a.item))
    c.commit()
    res = out("attempt-recorded", id=a.item, attempt=attempt_id, state=state)
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
        held = c.execute("SELECT COUNT(*) FROM work_item w WHERE w.state='running'"
                         + (" AND w.project=?" if a.project else ""),
                         ([a.project] if a.project else [])).fetchone()[0]
        if held:
            word, kw = "held-by-other", {"held": held, "project": a.project or "*",
                                         "hint": "every item for this project is leased; try `work.py reap`"}
        else:
            word, kw = "nothing-todo", {"project": a.project or "*"}
        if a.json:
            print(json.dumps(dict(kw, ok=word), sort_keys=True))
            return 0
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
    return rc


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
    return out("selftest-ok", db=str(tmp), exclusive_claims=got)


# ---------------------------------------------------------------- cli

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
    at.set_defaults(func=cmd_attempt)

    dn = sub.add_parser("done")
    dn.add_argument("item", type=int)
    dn.add_argument("--by", default=whoami())
    dn.add_argument("--did")
    dn.add_argument("--proof")
    dn.add_argument("--result")
    dn.add_argument("--left")
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
