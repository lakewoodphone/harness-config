#!/usr/bin/env python3
"""chatindex — ingest every AI-chat history on this machine into a searchable index.

WHY. Measured on ZABZ-TECH 2026-09-14: the existing chat capture holds 1,009
sessions and 4,368 messages for seven months, while `%APPDATA%\\Code\\User\\
workspaceStorage` carries **17 GB across 737 `chatSessions/*.jsonl` files** (42 of
them over 100 MB, the largest 1,050 MB). Almost none of it was ever ingested, so
questions about the owner's own history are answered from 1% of the record.

WHAT IT READS (discovered, not assumed)
  * `chatSessions/*.jsonl` — an append-log. Each line is one JSON object:
      {"kind":0,"v":{...}}                      session header (sessionId, creationDate)
      {"kind":1,"k":["customTitle"],"v":"..."}  a property the UI set later
      {"kind":2,"k":["requests"],"v":[ {...}, ... ]}  one or more finished requests
    Inside a request: `message.text` is the human turn, `response` an array whose
    string entries are the assistant's prose, `modelId`, `timestamp`,
    `contentReferences[]`. Verified against a 39.8 MB real file.
  * `transcripts/*.jsonl` and `%USERPROFILE%\\.copilot\\session-state` when present.

DESIGN, each point because of a measurement
  * STREAMING, line by line. The largest file is 1,050 MB; loading it whole would
    cost more memory than the machine should give a background job.
  * RESUME BY BYTE OFFSET. The log is append-only, so a file that grew is read
    from where the last run stopped. A 1 GB file is never re-read to pick up its
    last turn.
  * HARD CAPS per request. One turn in the sample carried 5,717 chars; some carry
    a tool dump far larger. The cap keeps one runaway turn from owning the index.
  * SKIPS TOOL NOISE. `metadata.toolCallResults` is megabytes of terminal output
    and file bodies; indexing it would drown the human record it is attached to.

USAGE
  chatindex.py index [--root DIR]... [--db PATH] [--verbose]
  chatindex.py search "term" [--limit N] [--role user|assistant]
  chatindex.py stats
  chatindex.py sessions [--limit N]
"""
from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1
MAX_TURN_CHARS = 20_000       # per human/assistant turn
MAX_FIELD_CHARS = 600         # titles, model ids, paths

DEFAULT_ROOTS = []
_A = os.environ.get("APPDATA")
if _A:
    DEFAULT_ROOTS += [
        os.path.join(_A, "Code", "User", "workspaceStorage"),
        os.path.join(_A, "Code - Insiders", "User", "workspaceStorage"),
        os.path.join(_A, "Cursor", "User", "workspaceStorage"),
    ]
_H = os.path.expanduser("~")
DEFAULT_ROOTS += [os.path.join(_H, ".copilot", "session-state"),
                  os.path.join(_H, ".dsh", "sessions")]


def connect(db_path):
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id        TEXT PRIMARY KEY,
            source    TEXT,
            path      TEXT,
            title     TEXT,
            model     TEXT,
            workspace TEXT,
            created   REAL,
            updated   REAL,
            turns     INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS messages (
            id        INTEGER PRIMARY KEY,
            session   TEXT NOT NULL,
            role      TEXT NOT NULL,
            ts        REAL,
            text      TEXT NOT NULL,
            model     TEXT,
            refs      TEXT,
            source    TEXT,
            path      TEXT
        );
        CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session);
        CREATE INDEX IF NOT EXISTS idx_msg_role ON messages(role);
        CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);

        CREATE VIRTUAL TABLE IF NOT EXISTS msg_fts USING fts5(
            text, session UNINDEXED, role UNINDEXED,
            tokenize='porter unicode61'
        );
        CREATE VIRTUAL TABLE IF NOT EXISTS msg_tri USING fts5(
            text, session UNINDEXED, role UNINDEXED,
            tokenize='trigram'
        );
        -- append-only progress so a grown file is read from where we stopped
        CREATE TABLE IF NOT EXISTS ingest (
            path     TEXT PRIMARY KEY,
            size     INTEGER,
            mtime    REAL,
            offset   INTEGER DEFAULT 0,
            messages INTEGER DEFAULT 0,
            sessions INTEGER DEFAULT 0,
            last_run TEXT
        );
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    con.commit()
    return con


def _clip(s, n=MAX_TURN_CHARS):
    if not isinstance(s, str):
        return None
    s = s.strip()
    if not s:
        return None
    return s[:n]


def extract_from_line(obj):
    """Yield (kind, payload) for every human/assistant turn in one JSONL record."""
    if not isinstance(obj, dict):
        return
    kind = obj.get("kind")
    if kind == 0:
        v = obj.get("v") or {}
        yield "header", v
        return
    if kind == 1:
        keys = obj.get("k") or []
        if "customTitle" in keys:
            yield "title", obj.get("v")
        return
    if kind == 2 and (obj.get("k") or []) == ["requests"]:
        for req in (obj.get("v") or []):
            if isinstance(req, dict):
                yield "request", req


def turns_from_request(req):
    """The human turn, then the assistant's prose. Tool output is deliberately dropped."""
    ts = req.get("timestamp")
    try:
        ts = float(ts) / 1000.0 if ts and ts > 1e11 else float(ts or 0)
    except (TypeError, ValueError):
        ts = None
    model = req.get("modelId")
    if isinstance(model, dict):
        model = model.get("id") or model.get("identifier")

    msg = req.get("message")
    human = None
    if isinstance(msg, dict):
        human = _clip(msg.get("text"))
    elif isinstance(msg, str):
        human = _clip(msg)
    if human:
        refs = []
        for ref in (req.get("contentReferences") or [])[:20]:
            try:
                p = (ref.get("reference") or {}).get("fsPath")
                if p:
                    refs.append(p)
            except AttributeError:
                pass
        yield ("user", human, ts, model, "; ".join(refs)[:2000])

    resp = req.get("response")
    parts = []
    if isinstance(resp, list):
        for item in resp:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("value", "text", "content"):
                    v = item.get(key)
                    if isinstance(v, str):
                        parts.append(v)
    elif isinstance(resp, str):
        parts.append(resp)
    asst = _clip("\n".join(p for p in parts if p))
    if asst:
        yield ("assistant", asst, ts, model, None)


def ingest_file(con, path, source, verbose=False):
    st = os.stat(path)
    row = con.execute("SELECT size, offset FROM ingest WHERE path=?", (path,)).fetchone()
    offset = 0
    if row and int(row["size"]) <= st.st_size:
        offset = int(row["offset"] or 0)
    elif row:
        # the file shrank: it was rotated or replaced, so start over
        con.execute("DELETE FROM messages WHERE path=?", (path,))
        offset = 0

    session_id = os.path.splitext(os.path.basename(path))[0]
    title = None
    model = None
    created = None
    turns = 0
    workspace = os.path.basename(os.path.dirname(os.path.dirname(path)))

    with open(path, "rb") as fh:
        if offset:
            fh.seek(offset)
        buf = b""
        pos = offset
        while True:
            chunk = fh.read(1 << 20)
            if not chunk:
                break
            buf += chunk
            while b"\n" in buf:
                line, _, buf = buf.partition(b"\n")
                pos += len(line) + 1
                if not line.strip():
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                for what, payload in extract_from_line(obj):
                    if what == "header":
                        session_id = payload.get("sessionId") or session_id
                        created = payload.get("creationDate")
                        if isinstance(created, (int, float)) and created > 1e11:
                            created = created / 1000.0
                    elif what == "title":
                        title = _clip(payload, MAX_FIELD_CHARS)
                    elif what == "request":
                        for role, text, ts, mdl, refs in turns_from_request(payload):
                            cur = con.execute(
                                "INSERT INTO messages(session, role, ts, text, model, refs,"
                                " source, path) VALUES(?,?,?,?,?,?,?,?)",
                                (session_id, role, ts, text, mdl, refs, source, path))
                            mid = cur.lastrowid
                            con.execute("INSERT INTO msg_fts(text, session, role) "
                                        "VALUES(?,?,?)", (text, session_id, role))
                            con.execute("INSERT INTO msg_tri(text, session, role) "
                                        "VALUES(?,?,?)", (text, session_id, role))
                            turns += 1
                            if mdl:
                                model = mdl
        # a trailing partial line (crash) is left in buf and picked up next run
        offset = pos

    # session row
    existing = con.execute("SELECT turns FROM sessions WHERE id=?", (session_id,)).fetchone()
    if existing:
        con.execute("UPDATE sessions SET title=COALESCE(?,title), model=COALESCE(?,model),"
                    " created=COALESCE(created,?), updated=?, turns=turns+? WHERE id=?",
                    (title, model, created, st.st_mtime, turns, session_id))
    else:
        con.execute("INSERT INTO sessions(id, source, path, title, model, workspace,"
                    " created, updated, turns) VALUES(?,?,?,?,?,?,?,?,?)",
                    (session_id, source, path, title, model, workspace, created,
                     st.st_mtime, turns))

    con.execute(
        "INSERT INTO ingest(path, size, mtime, offset, messages, sessions, last_run) "
        "VALUES(?,?,?,?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
        "size=excluded.size, mtime=excluded.mtime, offset=excluded.offset, "
        "messages=ingest.messages+excluded.messages, last_run=excluded.last_run",
        (path, st.st_size, st.st_mtime, offset, turns, 1,
         dt.datetime.now(dt.timezone.utc).isoformat()))
    con.commit()
    return turns


def discover(roots):
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        # chatSessions and transcripts under workspaceStorage, plus direct *.jsonl
        for pat in ("**/chatSessions/*.jsonl", "**/transcripts/*.jsonl", "*.jsonl",
                    "**/session-state/**/*.json", "**/*.jsonl"):
            for p in glob.glob(os.path.join(root, pat), recursive=True):
                found.append(p)
    seen, out = set(), []
    for p in found:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def do_index(con, roots, verbose=False, limit=None):
    t0 = time.time()
    files = discover(roots)
    files.sort(key=os.path.getsize)   # small first: fast feedback
    if limit:
        files = files[:limit]
    total_turns = new_files = 0
    for i, path in enumerate(files, 1):
        try:
            n = ingest_file(con, path, "vscode", verbose=verbose)
        except (OSError, ValueError, sqlite3.Error) as exc:
            print(f"  ! {path}: {exc}")
            continue
        total_turns += n
        if n:
            new_files += 1
        if verbose and i % 25 == 0:
            print(f"    {i}/{len(files)} files, {total_turns} turns, "
                  f"{time.time()-t0:.0f}s", flush=True)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_index',?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_seconds',?)",
                (f"{time.time()-t0:.1f}",))
    con.commit()
    return {"files": len(files), "with_new": new_files, "turns": total_turns,
            "seconds": round(time.time() - t0, 1)}


def do_search(con, term, limit, role, exact):
    if exact:
        sql = ("SELECT m.role, m.session, m.ts, m.text FROM msg_tri t "
               "JOIN messages m ON m.id = t.rowid WHERE msg_tri MATCH ?")
        params = [f'"{term}"']
    else:
        sql = ("SELECT m.role, m.session, m.ts, m.text FROM msg_fts t "
               "JOIN messages m ON m.id = t.rowid WHERE msg_fts MATCH ? "
               "ORDER BY bm25(msg_fts)")
        params = [term]
    if role:
        sql += " AND m.role = ?"
        params.append(role)
    sql += " LIMIT ?"
    params.append(limit)
    return con.execute(sql, params).fetchall()


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=os.path.join(_H, ".fsearch", "chats.db"))
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--root", action="append")
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--limit", type=int)
    p = sub.add_parser("search")
    p.add_argument("term")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--role", choices=["user", "assistant"])
    p.add_argument("--exact", action="store_true")
    p = sub.add_parser("stats")
    p = sub.add_parser("sessions")
    p.add_argument("--limit", type=int, default=20)
    a = ap.parse_args()

    con = connect(a.db)
    if a.cmd == "index":
        res = do_index(con, a.root or DEFAULT_ROOTS, verbose=a.verbose, limit=a.limit)
        print(f"files scanned={res['files']} with new turns={res['with_new']} "
              f"turns={res['turns']} in {res['seconds']}s")
    elif a.cmd == "search":
        rows = do_search(con, a.term, a.limit, a.role, a.exact)
        for r in rows:
            when = (dt.datetime.fromtimestamp(r["ts"], dt.timezone.utc).strftime("%Y-%m-%d")
                    if r["ts"] else "?")
            snip = " ".join((r["text"] or "").split())
            hit = snip.lower().find(a.term.lower().split()[0])
            start = max(0, hit - 90)
            print(f"  [{r['role'][:4]}] {when} {r['session'][:8]}  …{snip[start:start+220]}")
        print(f"({len(rows)} of up to {a.limit})")
    elif a.cmd == "sessions":
        for r in con.execute("SELECT id, title, model, turns, updated FROM sessions "
                             "ORDER BY turns DESC LIMIT ?", (a.limit,)):
            t = (dt.datetime.fromtimestamp(r["updated"], dt.timezone.utc).strftime("%Y-%m-%d")
                 if r["updated"] else "?")
            print(f"  {r['turns']:>5} turns  {t}  {r['id'][:8]}  "
                  f"{(r['title'] or '(untitled)')[:70]}")
    else:
        s = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        y = con.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
        a_ = con.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
        n = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        ing = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        meta = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
        print(f"sessions indexed : {n:,}")
        print(f"messages         : {s:,}  (user {y:,} / assistant {a_:,})")
        print(f"files ingested   : {ing:,}")
        print(f"last index       : {meta.get('last_index')} ({meta.get('last_seconds')}s)")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
