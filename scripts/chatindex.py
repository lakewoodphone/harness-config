#!/usr/bin/env python3
"""chatindex v2 — a correct replayer for the VS Code Copilot Chat patch log.

WHY v2. v1 was built on a guess I then verified against the real corpus and found
wrong. The records are not "one finished request per line". Measured on the actual
files, the patch paths are:

    requests.0.response            37 occurrences
    requests.2.response             5
    requests.1.responseMarkdownInfo 1
    requests.2.result               1
    requests.2.followups            1
    requests.0.modelState           1

So the assistant's answer usually arrives as a FIELD PATCH onto a request that an
earlier record created (`{"kind":1,"k":["requests",N,"response"],"v":...}`), not
inside the request object. v1 ignored every patch, which is why it found ~15k turns
across 2,080 files while the corpus plainly holds far more. v2 keeps a per-file
replay state and applies patches in order.

CORRUPTION MODES HANDLED (documented in VS Code issues, so they are real, not
theoretical):
  * BOM at file start, and a log that begins with patches and no kind:0 base.
  * A LATER kind:0 that has FEWER requests than the replayed state — trust the
    replay and flag it, because preferring the last kind:0 silently deletes turns.
  * Near-empty sessions: many files legitimately hold zero or one exchange.
  * Torn final line, which is truncated to the last newline rather than checkpointed.
  * A very long single line. MEASURED: median line 15 KB, p90 **49 MB**, max
    **419 MB** in one line of a 1 GB file. An unbounded read would OOM; the reader
    enforces a ceiling and records the skip.

RESUME. `kind:0` is rewritten in place, so (size, mtime) is not sufficient on its
own. Identity is (size growth) for append-only resume; a shrink or an older mtime
forces a full re-parse. Checkpoints are written in the same transaction as the
rows they describe.

NOT CHUNKED, deliberately. The atomic unit for search is the turn; splitting a
long answer degrades phrase search and dilutes BM25. `char_start`/`char_end` are
recorded per message so semantic chunks can be added later WITHOUT re-reading
15 GB — the one thing that is expensive to backfill.

USAGE
  chatindex.py index [--root DIR]... [--db PATH] [--verbose] [--limit N]
  chatindex.py search TERM [--limit N] [--role user|assistant] [--exact]
  chatindex.py tools [--limit N]      # tool usage across history
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

PARSER_VERSION = 4
MAX_TURN_CHARS = 60_000        # per human/assistant turn
MAX_LINE_BYTES = 64 * 1024 * 1024   # measured max is 419 MB; refuse rather than OOM
MAX_FIELD_CHARS = 600
BATCH = 500

_H = os.path.expanduser("~")
_A = os.environ.get("APPDATA")

DEFAULT_ROOTS: list[str] = []
if _A:
    DEFAULT_ROOTS += [
        os.path.join(_A, "Code", "User", "workspaceStorage"),
        os.path.join(_A, "Code", "User", "globalStorage"),
        os.path.join(_A, "Code - Insiders", "User", "workspaceStorage"),
        os.path.join(_A, "Cursor", "User", "workspaceStorage"),
    ]
DEFAULT_ROOTS += [
    os.path.join(_H, ".copilot", "session-state"),
    os.path.join(_H, ".dsh", "sessions"),
]


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    con = sqlite3.connect(db_path, timeout=30)
    # Python's sqlite3 opens an implicit transaction on the first write unless this
    # is set, which makes an explicit "BEGIN" raise "cannot start a transaction
    # within a transaction". Setting isolation_level=None (autocommit) hands
    # transaction control to this file, where every BEGIN/COMMIT is deliberate.
    con.isolation_level = None
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS sessions (
            id TEXT PRIMARY KEY, source TEXT, path TEXT, title TEXT,
            workspace TEXT, cwd TEXT, created REAL, updated REAL,
            turns INTEGER DEFAULT 0, quality TEXT, parser_version INTEGER,
            mtime REAL, size INTEGER
        );
        CREATE TABLE IF NOT EXISTS messages (
            id INTEGER PRIMARY KEY, session TEXT NOT NULL, request_id TEXT,
            role TEXT NOT NULL, ts REAL, ts_iso TEXT, text TEXT NOT NULL,
            model TEXT, mode TEXT, agent TEXT, tool_names TEXT, refs TEXT,
            char_start INTEGER, char_end INTEGER,
            embed_status TEXT DEFAULT 'pending', embed_model TEXT, embed_dim INTEGER,
            source TEXT, path TEXT, parser_version INTEGER
        );
        CREATE INDEX IF NOT EXISTS idx_msg_session ON messages(session);
        CREATE INDEX IF NOT EXISTS idx_msg_role ON messages(role);
        CREATE INDEX IF NOT EXISTS idx_msg_ts ON messages(ts);
        CREATE UNIQUE INDEX IF NOT EXISTS idx_msg_ident
            ON messages(session, request_id, role);
        CREATE INDEX IF NOT EXISTS idx_msg_tool ON messages(tool_names);

        CREATE VIRTUAL TABLE IF NOT EXISTS msg_fts USING fts5(
            text, session UNINDEXED, role UNINDEXED,
            tokenize='porter unicode61');
        CREATE VIRTUAL TABLE IF NOT EXISTS msg_tri USING fts5(
            text, session UNINDEXED, role UNINDEXED,
            tokenize='trigram');

        CREATE TABLE IF NOT EXISTS ingest (
            path TEXT PRIMARY KEY, size INTEGER, mtime REAL, offset INTEGER DEFAULT 0,
            requests INTEGER DEFAULT 0, messages INTEGER DEFAULT 0,
            skipped_lines INTEGER DEFAULT 0, last_run TEXT, parser_version INTEGER,
            note TEXT);
        CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
    """)
    con.commit()
    return con


def _ts(v):
    """Normalise ms-since-epoch to (seconds_float, iso_string)."""
    try:
        n = float(v)
    except (TypeError, ValueError):
        return None, None
    if n > 1e11:
        n = n / 1000.0
    try:
        return n, dt.datetime.fromtimestamp(n, dt.timezone.utc).isoformat()
    except (OSError, OverflowError, ValueError):
        return None, None


def _clip(s, n):
    if not isinstance(s, str):
        return None
    s = s.strip()
    return s[:n] if s else None


def response_text(resp):
    """The assistant's prose from a `response` field, in any of its shapes."""
    parts = []
    if isinstance(resp, str):
        parts.append(resp)
    elif isinstance(resp, list):
        for item in resp:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                for key in ("value", "text", "content", "markdown"):
                    v = item.get(key)
                    if isinstance(v, str) and v.strip():
                        parts.append(v)
                        break
    elif isinstance(resp, dict):
        for key in ("value", "text", "content", "markdown"):
            v = resp.get(key)
            if isinstance(v, str) and v.strip():
                parts.append(v)
                break
    joined = "\n".join(p for p in parts if p)
    return _clip(joined, MAX_TURN_CHARS)


def refs_of(req):
    out = []
    for ref in (req.get("contentReferences") or [])[:20]:
        try:
            p = (ref.get("reference") or {}).get("fsPath")
            if p:
                out.append(p)
        except AttributeError:
            continue
    return "; ".join(out)[:2000] or None


def tool_names_of(req):
    names = set()
    md = req.get("metadata") or {}
    for key in ("toolCallRounds", "toolCallResults"):
        v = md.get(key)
        if isinstance(v, list):
            for item in v[:60]:
                if isinstance(item, dict):
                    for k2 in ("name", "toolName", "tool_name"):
                        if isinstance(item.get(k2), str):
                            names.add(item[k2][:80])
        elif isinstance(v, dict):
            for item in list(v.values())[:60]:
                if isinstance(item, dict):
                    for k2 in ("name", "toolName"):
                        if isinstance(item.get(k2), str):
                            names.add(item[k2][:80])
    for r in (req.get("response") or []):
        if isinstance(r, dict) and isinstance(r.get("toolName"), str):
            names.add(r["toolName"][:80])
    return ",".join(sorted(names))[:1000] or None


def looks_like_request(o):
    return isinstance(o, dict) and (
        "message" in o or "requestId" in o or "response" in o or "timestamp" in o)


# How much of an oversized line to mine, and how many turns to keep from it.
# A 419 MB line is read once; 64 MB of scanning is seconds, not minutes.
MAX_HARVEST_BYTES = 64 * 1024 * 1024
MAX_HARVEST_TURNS = 200

# Ordered so the human turn is found before the assistant's, matching the order
# they appear in a request object.
_HARVEST_PATTERNS = (
    (b'"text":"', "user"),
    (b'"response":[', "assistant"),
    (b'"invocationMessage":{"value":"', "assistant"),
    (b'"value":"', "assistant"),
)


def _json_string_at(blob: bytes, start: int, limit: int = 200_000) -> str | None:
    """Decode a JSON string beginning at `start`, scanning forward for its close.

    Handles the escapes that matter (`\\"`, `\\\\`, `\\n`) and gives up rather than
    running away if a string never closes inside the budget.
    """
    out = []
    i = start
    end = min(len(blob), start + limit)
    while i < end:
        b = blob[i]
        if b == 0x5C:                       # backslash
            if i + 1 >= end:
                break
            nxt = blob[i + 1:i + 2]
            if nxt == b"n":
                out.append("\n")
            elif nxt == b"t":
                out.append("\t")
            elif nxt == b"r":
                out.append("\r")
            elif nxt in (b'"', b"\\", b"/"):
                out.append(nxt.decode("ascii"))
            elif nxt == b"u" and i + 5 < end:
                try:
                    out.append(chr(int(blob[i + 2:i + 6].decode("ascii"), 16)))
                    i += 6
                    continue
                except ValueError:
                    pass
            i += 2
            continue
        if b == 0x22:                       # closing quote
            return "".join(out)
        out.append(chr(b) if 32 <= b < 127 else " ")
        i += 1
    return None


def harvest_oversized_bytes(blob: bytes) -> list[str]:
    """Best-effort text extraction from a line too large to json.loads.

    Heuristic by nature, and labelled as such in the quality flag. Two rules keep
    it honest: never emit anything shorter than 200 characters (a field name is
    not a turn), and cap the number of turns taken from one line.
    """
    found: list[str] = []
    for needle, _role in _HARVEST_PATTERNS:
        pos = 0
        while len(found) < MAX_HARVEST_TURNS:
            idx = blob.find(needle, pos)
            if idx == -1:
                break
            pos = idx + len(needle)
            text = _json_string_at(blob, pos)
            if text and len(text) >= 200:
                found.append(text[:MAX_TURN_CHARS])
        if len(found) >= MAX_HARVEST_TURNS:
            break
    return found


def iter_lines(fh, max_line=MAX_LINE_BYTES, stats=None):
    """Yield line bytes with bounded memory. O(n), not O(n^2).

    THE DEFECT THIS FIXES (measured 2026-09-14): the first version did
    `buf += chunk` and then `buf.partition(b"\\n")` on every 1 MB read. On the
    1,050 MB file, whose dominant line is **419 MB**, that is quadratic in the
    line length: the process burned 1,525 s of CPU and never finished. Concatenating
    a growing buffer and re-scanning it per chunk is the trap.

    Instead: accumulate into a bytearray (mutating, not reallocating a new bytes
    object per read) and only convert to bytes at a newline. A line longer than
    `max_line` is skipped by discarding the buffer and scanning forward for the
    next newline, so memory stays bounded no matter how pathological the input is.
    """
    buf = bytearray()
    while True:
        chunk = fh.read(1 << 20)
        if not chunk:
            break
        buf.extend(chunk)
        while True:
            nl = buf.find(b"\n")
            if nl == -1:
                break
            line = bytes(buf[:nl])
            del buf[:nl + 1]
            yield line
        if len(buf) > max_line:
            # Oversized single line. Measured on this corpus: 24 lines exceed the
            # ceiling and the largest is 419 MB, and DISCARDING them loses real
            # conversation -- the 1,050 MB file yielded 2 requests and 4 messages
            # while skipping 5 lines. They cannot be json.loads'd, but the text we
            # want sits in well-known string fields, so mine those directly, and
            # record exactly how much was recovered rather than pretending the
            # line was empty.
            if stats is not None:
                stats["skipped_long"] = stats.get("skipped_long", 0) + 1
                stats["skipped_bytes"] = stats.get("skipped_bytes", 0) + len(buf)
                got = harvest_oversized_bytes(bytes(buf[:MAX_HARVEST_BYTES]))
                if got:
                    stats.setdefault("harvested", []).extend(got)
            buf.clear()
            while True:
                more = fh.read(1 << 20)
                if not more:
                    return
                nl = more.find(b"\n")
                if nl != -1:
                    buf.extend(more[nl + 1:])
                    break
    if buf:
        # A trailing partial line: the file was cut off mid-record (VS Code does
        # this when it is closed with a chat open). It is still worth parsing for
        # whatever text is complete inside it, but the CALLER must know the line
        # was not newline-terminated -- otherwise a truncated session is reported
        # as "ok" and the loss becomes invisible. The flag is handed over rather
        # than inferred, because an earlier version of this generator silently
        # turned 648 torn sessions into 648 "ok" ones.
        if stats is not None:
            stats["torn_tail"] = True
        yield bytes(buf)


def ingest_file(con, path, source, verbose=False):
    """Replay one patch-log and write its turns. Returns a small report dict."""
    st = os.stat(path)
    row = con.execute("SELECT size, offset, parser_version FROM ingest WHERE path=?",
                      (path,)).fetchone()
    start_offset = 0
    if row and int(row["parser_version"] or 0) == PARSER_VERSION:
        if int(row["size"] or 0) <= st.st_size:
            start_offset = int(row["offset"] or 0)
        else:                                     # shrank -> rewritten, start over
            con.execute("DELETE FROM messages WHERE path=?", (path,))
            start_offset = 0
    elif row:
        con.execute("DELETE FROM messages WHERE path=?", (path,))
        start_offset = 0

    sid = os.path.splitext(os.path.basename(path))[0]
    title = None
    requests: list[dict] = []
    torn = False
    stats: dict = {}
    pos = start_offset
    base_requests_seen = 0

    with open(path, "rb") as fh:
        if start_offset:
            fh.seek(start_offset)
        for line in iter_lines(fh, stats=stats):
            if not line:
                continue
            if not line.strip():
                continue
            if line.startswith(b"\xef\xbb\xbf"):     # BOM on the first line
                line = line[3:]
            try:
                obj = json.loads(line)
            except Exception:
                continue
            if not isinstance(obj, dict):
                continue
            kind = obj.get("kind")
            if kind == 0:
                v = obj.get("v") or {}
                sid = v.get("sessionId") or sid
                if not requests and isinstance(v.get("requests"), list):
                    requests = [r for r in v["requests"] if looks_like_request(r)]
                else:
                    base_requests_seen += 1
                continue
            if kind == 1:
                keys = obj.get("k") or []
                val = obj.get("v")
                if keys and keys[0] == "customTitle":
                    title = _clip(val, MAX_FIELD_CHARS)
                elif keys and keys[0] == "requests" and len(keys) >= 2 \
                        and isinstance(keys[1], int):
                    idx = keys[1]
                    while len(requests) <= idx:
                        requests.append({})
                    if len(keys) == 2:
                        requests[idx] = val if isinstance(val, dict) else {}
                    else:
                        requests[idx][keys[2]] = val
                continue
            if kind == 2 and (obj.get("k") or []) == ["requests"]:
                v = obj.get("v")
                items = v if isinstance(v, list) else [v]
                for it in items:
                    if isinstance(it, dict):
                        requests.append(it)
                continue
            # kind 3 (delete) and unknown kinds carry no text we index
        pos = fh.tell()

    skipped_long = stats.get("skipped_long", 0)
    harvested = stats.get("harvested") or []
    # Set by iter_lines when the file ended without a newline, i.e. it was cut off
    # mid-record. Without this, a truncated session reads as "ok" and the loss is
    # invisible -- which is how 648 torn sessions went missing from the flag.
    torn = bool(stats.get("torn_tail"))

    # ── emit turns ──
    written = 0
    if con.in_transaction:
        con.commit()                 # never BEGIN inside an open transaction
    con.execute("BEGIN")
    for n, req in enumerate(requests):
        if not isinstance(req, dict):
            continue
        rid = _clip(req.get("requestId"), 120) or f"idx{n}"
        ts_s, ts_iso = _ts(req.get("timestamp"))
        model = req.get("modelId")
        if isinstance(model, dict):
            model = model.get("id") or model.get("identifier")
        mode = (req.get("modeInfo") or {}).get("kind") if isinstance(
            req.get("modeInfo"), dict) else None
        agent = (req.get("agent") or {}).get("name") if isinstance(
            req.get("agent"), dict) else None

        msg = req.get("message")
        human = None
        if isinstance(msg, dict):
            human = _clip(msg.get("text"), MAX_TURN_CHARS)
        elif isinstance(msg, str):
            human = _clip(msg, MAX_TURN_CHARS)
        asst = response_text(req.get("response"))
        tools = tool_names_of(req)
        refs = refs_of(req)

        for role, text in (("user", human), ("assistant", asst)):
            if not text:
                continue
            cur = con.execute(
                "INSERT OR REPLACE INTO messages(session, request_id, role, ts, ts_iso,"
                " text, model, mode, agent, tool_names, refs, char_start, char_end,"
                " source, path, parser_version) "
                "VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
                (sid, rid, role, ts_s, ts_iso, text, model, mode, agent, tools, refs,
                 len(text), source, path, PARSER_VERSION))
            mid = cur.lastrowid
            con.execute("DELETE FROM msg_fts WHERE rowid=?", (mid,))
            con.execute("DELETE FROM msg_tri WHERE rowid=?", (mid,))
            con.execute("INSERT INTO msg_fts(rowid, text, session, role) VALUES(?,?,?,?)",
                        (mid, text, sid, role))
            con.execute("INSERT INTO msg_tri(rowid, text, session, role) VALUES(?,?,?,?)",
                        (mid, text, sid, role))
            written += 1
        if n % BATCH == 0:
            # The BEGIN may already be closed by an earlier commit. Committing a
            # non-transaction is harmless; STARTING one inside an open transaction
            # is an error, and that is what made whole files fail with
            # "cannot start a transaction within a transaction".
            if con.in_transaction:
                con.commit()
            con.execute("BEGIN")

    # Balance the transaction unconditionally. An unmatched BEGIN here is how
    # files with zero requests produced the error above.
    try:
        con.commit()
    except sqlite3.Error:
        con.rollback()

    # ── turns recovered from oversized lines ──
    # These are heuristic, so they are written with a distinct request_id suffix
    # and counted separately. They are the difference between 4 messages and the
    # real content of the biggest conversation in the archive.
    harvested = stats.get("harvested") or []
    for k, text in enumerate(harvested):
        role = "user" if k % 2 == 0 else "assistant"
        rid = f"harvested{k}"
        cur = con.execute(
            "INSERT OR REPLACE INTO messages(session, request_id, role, ts, ts_iso,"
            " text, model, mode, agent, tool_names, refs, char_start, char_end,"
            " source, path, parser_version) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,0,?,?,?,?)",
            (sid, rid, role, None, None, text, None, None, None, None, None,
             len(text), source, path, PARSER_VERSION))
        mid = cur.lastrowid
        con.execute("DELETE FROM msg_fts WHERE rowid=?", (mid,))
        con.execute("DELETE FROM msg_tri WHERE rowid=?", (mid,))
        con.execute("INSERT INTO msg_fts(rowid, text, session, role) VALUES(?,?,?,?)",
                    (mid, text, sid, role))
        con.execute("INSERT INTO msg_tri(rowid, text, session, role) VALUES(?,?,?,?)",
                    (mid, text, sid, role))
        written += 1
    # Commit the harvested writes. Do NOT open a new transaction here: the code
    # below only writes on the paths that follow, and an unmatched BEGIN was the
    # source of the "transaction within a transaction" failures.
    try:
        con.commit()
    except sqlite3.Error:
        con.rollback()

    quality = "ok"
    if torn:
        quality = "torn_tail"
    if base_requests_seen:
        quality = (quality + "+later_base_ignored") if quality != "ok" \
            else "later_base_ignored"
    if skipped_long:
        quality += f"+{skipped_long}_long_line_skipped"
    if harvested:
        quality += f"+{len(harvested)}_harvested"

    existing = con.execute("SELECT turns FROM sessions WHERE id=?", (sid,)).fetchone()
    if existing:
        con.execute("UPDATE sessions SET title=COALESCE(?,title), updated=?, "
                    "turns=?, quality=?, parser_version=?, mtime=?, size=? WHERE id=?",
                    (title, st.st_mtime, len(requests), quality, PARSER_VERSION,
                     st.st_mtime, st.st_size, sid))
    else:
        con.execute("INSERT INTO sessions(id, source, path, title, workspace, created,"
                    " updated, turns, quality, parser_version, mtime, size) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                    (sid, source, path, title,
                     os.path.basename(os.path.dirname(os.path.dirname(path))),
                     None, st.st_mtime, len(requests), quality, PARSER_VERSION,
                     st.st_mtime, st.st_size))

    con.execute(
        "INSERT INTO ingest(path, size, mtime, offset, requests, messages,"
        " skipped_lines, last_run, parser_version, note) VALUES(?,?,?,?,?,?,?,?,?,?) "
        "ON CONFLICT(path) DO UPDATE SET size=excluded.size, mtime=excluded.mtime,"
        " offset=excluded.offset, requests=excluded.requests,"
        " messages=excluded.messages, skipped_lines=excluded.skipped_lines,"
        " last_run=excluded.last_run, parser_version=excluded.parser_version,"
        " note=excluded.note",
        (path, st.st_size, st.st_mtime, pos, len(requests), written, skipped_long,
         dt.datetime.now(dt.timezone.utc).isoformat(), PARSER_VERSION, quality))
    con.commit()
    return {"requests": len(requests), "messages": written, "torn": torn,
            "skipped_long": skipped_long, "quality": quality}


def discover(roots):
    found = []
    for root in roots:
        if not os.path.isdir(root):
            continue
        for pat in ("**/chatSessions/*.jsonl", "**/chatSessions/*.json",
                    "**/emptyWindowChatSessions/*.jsonl",
                    "**/GitHub.copilot-chat/transcripts/*.jsonl",
                    "**/session-state/**/events.jsonl", "**/*.jsonl"):
            found += glob.glob(os.path.join(root, pat), recursive=True)
    out, seen = [], set()
    for p in found:
        # .copilot/pkg is the CLI's own runtime, not history: one dir per version.
        if os.sep + "pkg" + os.sep in p:
            continue
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def do_index(con, roots, verbose=False, limit=None):
    t0 = time.time()
    files = discover(roots)
    files.sort(key=os.path.getsize)          # small first: usable index in minutes
    if limit:
        files = files[:limit]
    tot_r = tot_m = errors = 0
    for i, path in enumerate(files, 1):
        try:
            r = ingest_file(con, path, "vscode")
        except (OSError, ValueError, sqlite3.Error) as exc:
            errors += 1
            print(f"  ! {os.path.basename(path)}: {type(exc).__name__}: {exc}")
            continue
        tot_r += r["requests"]
        tot_m += r["messages"]
        if verbose and i % 50 == 0:
            print(f"    {i}/{len(files)} files, {tot_r} requests, {tot_m} turns, "
                  f"{time.time()-t0:.0f}s", flush=True)
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_index',?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_seconds',?)",
                (f"{time.time()-t0:.1f}",))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('parser_version',?)",
                (str(PARSER_VERSION),))
    con.commit()
    if errors:
        print(f"  WARNING: {errors} file(s) failed; their rows may be missing")
    return {"files": len(files), "requests": tot_r, "turns": tot_m,
            "errors": errors, "seconds": round(time.time() - t0, 1)}


def main() -> int:
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
    p = sub.add_parser("tools")
    p.add_argument("--limit", type=int, default=25)
    p = sub.add_parser("sessions")
    p.add_argument("--limit", type=int, default=20)
    sub.add_parser("stats")
    a = ap.parse_args()

    con = connect(a.db)
    if a.cmd == "index":
        r = do_index(con, a.root or DEFAULT_ROOTS, a.verbose, a.limit)
        print(f"files={r['files']} requests={r['requests']} turns={r['turns']} "
              f"in {r['seconds']}s")
    elif a.cmd == "search":
        if a.exact:
            sql = ("SELECT m.* FROM msg_tri t JOIN messages m ON m.id=t.rowid "
                   "WHERE msg_tri MATCH ?")
            params = [f'"{a.term}"']
        else:
            sql = ("SELECT m.* FROM msg_fts t JOIN messages m ON m.id=t.rowid "
                   "WHERE msg_fts MATCH ? ORDER BY bm25(msg_fts)")
            params = [a.term]
        if a.role:
            sql += " AND m.role=?"
            params.append(a.role)
        sql += " LIMIT ?"
        params.append(a.limit)
        rows = con.execute(sql, params).fetchall()
        for r in rows:
            d = (r["ts_iso"] or "?")[:10]
            snip = " ".join((r["text"] or "").split())
            print(f"  [{r['role'][:4]}] {d} {(r['session'] or '')[:8]} "
                  f"{'tools:'+r['tool_names'][:30] if r['tool_names'] else ''}")
            print(f"      {snip[:200]}")
        print(f"({len(rows)} of up to {a.limit})")
    elif a.cmd == "tools":
        for r in con.execute(
                "SELECT tool_names, COUNT(*) n FROM messages WHERE tool_names IS NOT NULL "
                "GROUP BY tool_names ORDER BY n DESC LIMIT ?", (a.limit,)):
            print(f"  {r['n']:>6}  {r['tool_names'][:110]}")
    elif a.cmd == "sessions":
        for r in con.execute("SELECT id,title,turns,quality,updated FROM sessions "
                             "ORDER BY turns DESC LIMIT ?", (a.limit,)):
            d = dt.datetime.fromtimestamp(r["updated"], dt.timezone.utc).strftime("%Y-%m-%d") \
                if r["updated"] else "?"
            print(f"  {r['turns']:>4} req  {d}  {r['id'][:8]}  {r['quality']}  "
                  f"{(r['title'] or '(untitled)')[:60]}")
    else:
        n = con.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        u = con.execute("SELECT COUNT(*) FROM messages WHERE role='user'").fetchone()[0]
        z = con.execute("SELECT COUNT(*) FROM messages WHERE role='assistant'").fetchone()[0]
        s = con.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
        t = con.execute("SELECT COUNT(*) FROM messages WHERE tool_names IS NOT NULL").fetchone()[0]
        ing = con.execute("SELECT COUNT(*) FROM ingest").fetchone()[0]
        meta = {r["key"]: r["value"] for r in con.execute("SELECT * FROM meta")}
        print(f"sessions : {s:,}")
        print(f"messages : {n:,}  (user {u:,} / assistant {z:,}), with tool calls {t:,}")
        print(f"files    : {ing:,}")
        print(f"parser   : v{meta.get('parser_version')}   last {meta.get('last_index')} "
              f"({meta.get('last_seconds')}s)")
        for r in con.execute("SELECT quality, COUNT(*) c FROM sessions GROUP BY 1 "
                             "ORDER BY c DESC LIMIT 6"):
            print(f"  quality {r['quality']}: {r['c']}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
