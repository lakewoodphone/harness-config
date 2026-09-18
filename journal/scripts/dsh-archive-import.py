#!/usr/bin/env python3
"""dsh-archive-import.py — import one DSH session batch into the server-side archive.

WHY THIS EXISTS AS A STANDALONE SCRIPT
--------------------------------------
The intended home for this is the company app: `app/services/dsh_session_ingest.py`
(committed, staged) behind `POST /api/v1/owner/dsh-sessions/ingest`. It is **not
deployed**, because the authority's checkout of `personal-secretary-mvp` is **51
commits behind origin with nine uncommitted local modifications, including
`app/main.py`** — so deploying it means either a merge on a running company or a
hand-patch that deepens the drift. Neither is acceptable for a feature nobody is
waiting on tonight.

So the archive lives in its own SQLite database beside the spool, written by this
script, invoked over SSH by the shipper. Same tables, same semantics, same
idempotence; when the company checkout is reconciled, the tables move into
`secretary.db` and this file becomes the test harness for that move.

WHAT IT STORES
--------------
Durable session rows **verbatim** — one JSON object per line of the harness's own
journal, exactly as written, with the sequence number lifted out for indexing.
Nothing is expanded or interpreted: the official code that understands packed
`*-chunks` rows and folded surfaces is not exported by the installed harness
build, so re-implementing that reading here would be a confident guess about a
format we do not own (journal PAIN P22, LESSONS L51). `raw` is the source of
truth; anything richer is a view over it.

Idempotence: the primary key is (machine, session_id, ordinal), and the ordinal of
a durable row never moves because the journal is append-only. Re-importing the same
batch changes no row, which is what makes at-least-once delivery safe.

Usage:
  ssh <host> python3 dsh-archive-import.py < batch.json     # import
  ssh <host> python3 dsh-archive-import.py --stats          # coverage
  ssh <host> python3 dsh-archive-import.py --search "term"  # full-text search
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone

DEFAULT_DB = os.environ.get("DSH_ARCHIVE_DB", "/home/zabz/dsh-archive/dsh-archive.db")
SCHEMA_VERSION = 1
MAX_RAW_CHARS = 2_000_000


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def machine_name(value) -> str:
    raw = str(value or "unknown-machine").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_.-]+", "-", raw).strip("-.")
    return cleaned or "unknown-machine"


def sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="replace")).hexdigest()


def connect(db_path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    conn = sqlite3.connect(db_path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS dsh_session_exports (
            id              TEXT PRIMARY KEY,
            source_machine  TEXT NOT NULL,
            exported_at     TEXT,
            received_at     TEXT NOT NULL,
            schema_version  INTEGER DEFAULT 1,
            session_count   INTEGER DEFAULT 0,
            event_count     INTEGER DEFAULT 0,
            payload_bytes   INTEGER DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS dsh_sessions (
            source_machine  TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            project         TEXT DEFAULT '',
            cwd             TEXT DEFAULT '',
            preset          TEXT DEFAULT '',
            title           TEXT DEFAULT '',
            started_at      TEXT,
            file            TEXT DEFAULT '',
            file_bytes      INTEGER DEFAULT 0,
            frames          INTEGER DEFAULT 0,
            torn_tail       INTEGER DEFAULT 0,
            event_count     INTEGER DEFAULT 0,
            last_seq        INTEGER,
            content_hash    TEXT NOT NULL,
            metadata_json   TEXT DEFAULT '{}',
            ingested_at     TEXT NOT NULL,
            updated_at      TEXT NOT NULL,
            PRIMARY KEY (source_machine, session_id)
        );
        CREATE TABLE IF NOT EXISTS dsh_session_events (
            source_machine  TEXT NOT NULL,
            session_id      TEXT NOT NULL,
            ordinal         INTEGER NOT NULL,
            seq             INTEGER,
            type            TEXT DEFAULT '',
            raw             TEXT NOT NULL,
            created_at      TEXT,
            PRIMARY KEY (source_machine, session_id, ordinal)
        );
        CREATE INDEX IF NOT EXISTS idx_dsh_events_seq
            ON dsh_session_events(source_machine, session_id, seq);
        CREATE INDEX IF NOT EXISTS idx_dsh_sessions_recent
            ON dsh_sessions(updated_at DESC);
        """
    )
    try:
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS dsh_session_events_fts USING fts5("
            " source_machine UNINDEXED, session_id UNINDEXED, ordinal UNINDEXED, raw)"
        )
    except sqlite3.Error as exc:  # pragma: no cover - environment dependent
        print(json.dumps({"ok": False, "error": f"fts5 unavailable: {exc}"}))
        raise SystemExit(2)
    conn.commit()
    return conn


def row_text(value) -> str:
    text = value if isinstance(value, str) else str(value or "")
    if len(text) > MAX_RAW_CHARS:
        return text[:MAX_RAW_CHARS] + f'\n{{"truncated":true,"original_chars":{len(text)}}}'
    return text


def import_export(conn: sqlite3.Connection, export: dict) -> dict:
    source = machine_name(export.get("source_machine"))
    sessions = [s for s in (export.get("sessions") or []) if isinstance(s, dict)]
    now = now_iso()

    created = updated = unchanged = 0
    events_written = 0
    reindexed = 0

    payload_bytes = len(json.dumps(export).encode("utf-8", errors="replace"))
    export_id = f"{source}:{sha(json.dumps([s.get('session_id') for s in sessions]))[:16]}"
    conn.execute(
        """INSERT OR REPLACE INTO dsh_session_exports
           (id, source_machine, exported_at, received_at, schema_version,
            session_count, event_count, payload_bytes)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            export_id,
            source,
            str(export.get("exported_at") or "") or None,
            now,
            int(export.get("schema_version") or SCHEMA_VERSION),
            len(sessions),
            sum(len(s.get("rows") or []) for s in sessions),
            payload_bytes,
        ),
    )

    for session in sessions:
        session_id = str(session.get("session_id") or "").strip()
        if not session_id:
            continue
        rows = [r for r in (session.get("rows") or []) if isinstance(r, dict)]
        start_row = int(session.get("start_row") or 0)
        header = session.get("header") if isinstance(session.get("header"), dict) else {}

        fingerprint = sha(json.dumps([
            session.get("total_rows"),
            session.get("file_bytes"),
            [[r.get("seq"), r.get("type"), sha(str(r.get("raw") or ""))[:16]] for r in rows],
        ], sort_keys=True))

        existing = conn.execute(
            "SELECT content_hash, event_count FROM dsh_sessions WHERE source_machine=? AND session_id=?",
            (source, session_id),
        ).fetchone()
        is_new = existing is None
        same = (
            existing is not None
            and existing["content_hash"] == fingerprint
            and int(existing["event_count"] or 0) == int(session.get("total_rows") or 0)
        )

        conn.execute(
            """INSERT INTO dsh_sessions
               (source_machine, session_id, project, cwd, preset, title, started_at,
                file, file_bytes, frames, torn_tail, event_count, last_seq,
                content_hash, metadata_json, ingested_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
               ON CONFLICT(source_machine, session_id) DO UPDATE SET
                project=excluded.project, cwd=excluded.cwd, preset=excluded.preset,
                title=excluded.title, started_at=excluded.started_at, file=excluded.file,
                file_bytes=excluded.file_bytes, frames=excluded.frames,
                torn_tail=excluded.torn_tail, event_count=excluded.event_count,
                last_seq=excluded.last_seq, content_hash=excluded.content_hash,
                metadata_json=excluded.metadata_json, updated_at=excluded.updated_at""",
            (
                source,
                session_id,
                str(session.get("project") or ""),
                str(header.get("cwd") or session.get("cwd") or ""),
                str(header.get("agentPreset") or ""),
                str(header.get("title") or session.get("title") or "")[:500],
                str(header.get("createdAt") or "") or None,
                str(session.get("file") or ""),
                int(session.get("file_bytes") or 0),
                int(session.get("frames") or 0),
                1 if session.get("torn_tail") else 0,
                int(session.get("total_rows") or 0),
                max([r.get("seq") for r in rows if isinstance(r.get("seq"), int)], default=None),
                fingerprint,
                json.dumps({"header": header, "start_row": start_row}),
                now,
                now,
            ),
        )

        for offset, row in enumerate(rows):
            conn.execute(
                """INSERT INTO dsh_session_events
                   (source_machine, session_id, ordinal, seq, type, raw, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?)
                   ON CONFLICT(source_machine, session_id, ordinal) DO UPDATE SET
                    seq=excluded.seq, type=excluded.type, raw=excluded.raw""",
                (
                    source,
                    session_id,
                    start_row + offset,
                    row.get("seq") if isinstance(row.get("seq"), int) else None,
                    str(row.get("type") or "")[:80],
                    row_text(row.get("raw")),
                    now,
                ),
            )
            events_written += 1

        if rows and not same:
            conn.execute(
                "DELETE FROM dsh_session_events_fts WHERE source_machine=? AND session_id=?",
                (source, session_id),
            )
            conn.execute(
                """INSERT INTO dsh_session_events_fts (source_machine, session_id, ordinal, raw)
                   SELECT source_machine, session_id, ordinal, raw FROM dsh_session_events
                   WHERE source_machine=? AND session_id=?""",
                (source, session_id),
            )
            reindexed += 1

        if is_new:
            created += 1
        elif same:
            unchanged += 1
        else:
            updated += 1

    conn.commit()
    return {
        "ok": True,
        "source_machine": source,
        "sessions_created": created,
        "sessions_updated": updated,
        "sessions_unchanged": unchanged,
        "events_written": events_written,
        "sessions_reindexed": reindexed,
    }


def cmd_stats(db_path: str) -> dict:
    conn = connect(db_path)
    out = {
        "ok": True,
        "db": db_path,
        "sessions": conn.execute("SELECT COUNT(*) FROM dsh_sessions").fetchone()[0],
        "events": conn.execute("SELECT COUNT(*) FROM dsh_session_events").fetchone()[0],
        "indexed_rows": conn.execute("SELECT COUNT(*) FROM dsh_session_events_fts").fetchone()[0],
        "exports": conn.execute("SELECT COUNT(*) FROM dsh_session_exports").fetchone()[0],
        "latest_ingest": conn.execute("SELECT MAX(received_at) FROM dsh_session_exports").fetchone()[0],
        "by_machine": [
            {"machine": r["source_machine"], "sessions": r["n"], "events": r["events"], "latest": r["latest"]}
            for r in conn.execute(
                """SELECT source_machine, COUNT(*) n, SUM(event_count) events, MAX(updated_at) latest
                   FROM dsh_sessions GROUP BY source_machine ORDER BY n DESC"""
            )
        ],
    }
    return out


def cmd_search(db_path: str, query: str, limit: int) -> dict:
    conn = connect(db_path)
    rows = conn.execute(
        """SELECT f.source_machine, f.session_id, f.ordinal,
                  snippet(dsh_session_events_fts, 3, '[', ']', '…', 10) AS snippet,
                  s.cwd, s.updated_at
           FROM dsh_session_events_fts f
           LEFT JOIN dsh_sessions s
             ON s.source_machine=f.source_machine AND s.session_id=f.session_id
           WHERE dsh_session_events_fts MATCH ?
           ORDER BY rank LIMIT ?""",
        (query, max(1, min(limit, 100))),
    ).fetchall()
    return {"ok": True, "count": len(rows), "results": [dict(r) for r in rows]}


def main() -> int:
    ap = argparse.ArgumentParser(description="Import DSH session batches into the server archive")
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--stats", action="store_true")
    ap.add_argument("--search", metavar="QUERY")
    ap.add_argument("--limit", type=int, default=20)
    ap.add_argument(
        "--file",
        metavar="PATH",
        help="read the batch from a file instead of stdin. This is the preferred path: on some "
             "machines ssh stalls when several megabytes are streamed into a remote process on "
             "stdin (measured on ZABZ-TECH, 2026-09-11), while scp moves the same payload in "
             "fractions of a second.",
    )
    args = ap.parse_args()

    if args.stats:
        print(json.dumps(cmd_stats(args.db)))
        return 0
    if args.search:
        print(json.dumps(cmd_search(args.db, args.search, args.limit)))
        return 0

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8", errors="replace") as fh:
                raw = fh.read()
        except OSError as exc:
            print(json.dumps({"ok": False, "error": f"cannot read {args.file}: {exc}"}))
            return 2
    else:
        raw = sys.stdin.read()

    if not raw.strip():
        print(json.dumps({"ok": False, "error": "empty input"}))
        return 2
    try:
        export = json.loads(raw)
    except ValueError as exc:
        print(json.dumps({"ok": False, "error": f"invalid json: {exc}"}))
        return 2

    conn = connect(args.db)
    try:
        print(json.dumps(import_export(conn, export)))
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
