#!/usr/bin/env python3
"""commsindex — one searchable index over every conversation this business has.

THE GAP THIS CLOSES. Measured on the authority, 2026-09-14: the company database
holds a year of business communication and **not one byte of it is full-text
searchable**. There are 21 Dialpad tables and the FTS indexes that exist cover
email drafts, memories, project knowledge and chat exports — nothing for SMS,
calls or voicemails:

    dialpad_sms_cache              127,651 rows   2025-04-18 .. 2026-09-14  body_text
    dialpad_call_full               12,473 rows   2026-04-23 .. 2026-09-14  transcription_text
    dialpad_transcript_cache         4,052 rows   2026-04-12 .. 2026-09-14  transcript_text, recap_text
    dialpad_ui_message_body_row      6,194 rows                           body_text
    dialpad_ui_voicemail_row         3,036 rows                           transcript
    dialpad_ui_message_row          14,516 rows                           snippet
    dialpad_ui_history_row          10,703 rows                           snippet

So "what did that customer say about the water damage" or "which supplier quoted
me for screens in June" costs a full table scan if it is answerable at all.

WHAT IT BUILDS. A SQLite FTS5 database beside the other search indexes, with one
row per communication and a schema chosen so an agent can answer a question
without a second lookup:

    comms(kind, ts, day, direction, counterparty, address, text, meta)
    comms_fts over the same text    (porter unicode61: stemming)
    comms_tri over counterparty + text (trigram: substrings inside identifiers
                                        and phone numbers)

`kind` is one of sms / call / voicemail / message / history. `text` is the body,
transcript or recap. Everything is READ-ONLY: this never writes to the company
database.

USAGE
  commsindex.py index [--db PATH] [--source PATH] [--verbose]
  commsindex.py search TERM [--kind sms] [--limit 20]
  commsindex.py stats
  commsindex.py timeline [--kind sms] [--limit 30]
"""
from __future__ import annotations

import argparse
import datetime as dt
import os
import sqlite3
import sys
import time

SCHEMA_VERSION = 1

DEFAULT_SOURCE = "/home/zabz/personal-secretary-mvp/data/secretary.db"
DEFAULT_DB = os.path.expanduser("~/.fsearch/comms.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS comms (
    id           INTEGER PRIMARY KEY,
    kind         TEXT NOT NULL,
    ref          TEXT,            -- source row id / call id / message id
    ts           REAL,            -- epoch seconds, UTC
    day          TEXT,            -- YYYY-MM-DD for cheap grouping
    direction    TEXT,
    counterparty TEXT,
    address      TEXT,            -- phone number or thread id
    subject      TEXT,            -- voicemail label / history activity type
    text         TEXT NOT NULL,
    meta         TEXT,            -- short provenance: table + source key
    source_table TEXT
);
CREATE INDEX IF NOT EXISTS idx_comms_kind ON comms(kind);
CREATE INDEX IF NOT EXISTS idx_comms_day ON comms(day);
CREATE INDEX IF NOT EXISTS idx_comms_party ON comms(counterparty);
CREATE UNIQUE INDEX IF NOT EXISTS idx_comms_uniq ON comms(source_table, ref);

CREATE VIRTUAL TABLE IF NOT EXISTS comms_fts USING fts5(
    text, counterparty UNINDEXED, kind UNINDEXED, id UNINDEXED,
    tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS comms_tri USING fts5(
    text, counterparty, kind UNINDEXED,
    tokenize='trigram');

CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT);
"""


def connect(path: str) -> sqlite3.Connection:
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    con = sqlite3.connect(path, timeout=60)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.executescript(SCHEMA)
    con.commit()
    return con


def _ts_from(value) -> float | None:
    """Accept epoch ms, epoch s, ISO strings with or without a zone."""
    if value in (None, "", "None"):
        return None
    if isinstance(value, (int, float)):
        v = float(value)
        return v / 1000.0 if v > 1e11 else v
    s = str(value).strip()
    if not s:
        return None
    # dialpad_transcript_cache stores '2026-04-23 03:27 UTC'
    for fmt in ("%Y-%m-%d %H:%M UTC", "%Y-%m-%d %H:%M:%S UTC", "%Y-%m-%d %H:%M:%S"):
        try:
            return dt.datetime.strptime(s, fmt).replace(
                tzinfo=dt.timezone.utc).timestamp()
        except ValueError:
            continue
    try:
        d = dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.timestamp()


def _day(ts: float | None) -> str | None:
    if not ts:
        return None
    try:
        return dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")
    except (OSError, OverflowError, ValueError):
        return None


def _has_table(con: sqlite3.Connection, name: str) -> bool:
    return con.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
        (name,)).fetchone() is not None


# Each extractor yields dicts. Written as SQL + a row mapper so the shape of every
# source is explicit and auditable, rather than one clever generic query.
def rows_sms(src: sqlite3.Connection):
    sql = """SELECT id, message_id, created_at, direction, phone_normalized,
                    customer_name, body_text, channel
             FROM dialpad_sms_cache
             WHERE body_text IS NOT NULL AND TRIM(body_text) <> ''"""
    for r in src.execute(sql):
        yield {
            "kind": "sms", "ref": str(r["message_id"] or r["id"]),
            "ts": _ts_from(r["created_at"]), "direction": r["direction"],
            "counterparty": r["customer_name"], "address": r["phone_normalized"],
            "subject": r["channel"], "text": r["body_text"],
            "source_table": "dialpad_sms_cache",
        }


def rows_calls(src: sqlite3.Connection):
    sql = """SELECT call_id, direction, date_started_ms, contact_name, contact_phone,
                    external_number, contact_name, transcription_text, raw_payload,
                    duration_seconds, state
             FROM dialpad_call_full"""
    for r in src.execute(sql):
        text = (r["transcription_text"] or "").strip()
        # A call with no transcript is still a recorded event worth finding by
        # contact or number, so it is indexed with a short synthetic body rather
        # than being dropped -- "when did I last speak to X" must work.
        if not text:
            dur = r["duration_seconds"] or 0
            text = (f"[no transcript] {r['direction'] or ''} call "
                    f"{int(dur)}s state={r['state'] or ''}")
        yield {
            "kind": "call", "ref": str(r["call_id"]),
            "ts": _ts_from(r["date_started_ms"]),
            "direction": r["direction"],
            "counterparty": r["contact_name"],
            "address": r["contact_phone"] or r["external_number"],
            "subject": r["state"], "text": text,
            "source_table": "dialpad_call_full",
        }


def rows_transcripts(src: sqlite3.Connection):
    sql = """SELECT call_id, started_at, direction, phone_normalized,
                    transcript_text, recap_text, has_transcript, has_recap
             FROM dialpad_transcript_cache"""
    for r in src.execute(sql):
        t = (r["transcript_text"] or "").strip()
        c = (r["recap_text"] or "").strip()
        if not t and not c:
            continue
        yield {
            "kind": "call", "ref": f"tc:{r['call_id']}",
            "ts": _ts_from(r["started_at"]), "direction": r["direction"],
            "counterparty": None, "address": r["phone_normalized"],
            "subject": "transcript+recap" if (t and c) else "transcript",
            "text": (t + ("\n\nRECAP: " + c if c else "")),
            "source_table": "dialpad_transcript_cache",
        }


def rows_voicemails(src: sqlite3.Connection):
    sql = """SELECT vm_id, started_label, direction, phone_number, contact_name,
                    transcript, duration_text
             FROM dialpad_ui_voicemail_row"""
    for r in src.execute(sql):
        text = (r["transcript"] or "").strip()
        if not text:
            continue
        yield {
            "kind": "voicemail", "ref": str(r["vm_id"]),
            "ts": _ts_from(r["started_label"]), "direction": r["direction"],
            "counterparty": r["contact_name"], "address": r["phone_number"],
            "subject": r["duration_text"], "text": text,
            "source_table": "dialpad_ui_voicemail_row",
        }


def rows_message_bodies(src: sqlite3.Connection):
    sql = """SELECT id, thread_id, message_id, captured_at, contact_name,
                    phone_number, direction, body_text
             FROM dialpad_ui_message_body_row
             WHERE body_text IS NOT NULL AND TRIM(body_text) <> ''"""
    for r in src.execute(sql):
        yield {
            "kind": "message", "ref": str(r["message_id"] or r["id"]),
            "ts": _ts_from(r["captured_at"]), "direction": r["direction"],
            "counterparty": r["contact_name"], "address": r["phone_number"],
            "subject": None, "text": r["body_text"],
            "source_table": "dialpad_ui_message_body_row",
        }


def rows_messages(src: sqlite3.Connection):
    sql = """SELECT id, thread_id, captured_at, contact_name, phone_number,
                    snippet, started_label
             FROM dialpad_ui_message_row
             WHERE snippet IS NOT NULL AND TRIM(snippet) <> ''"""
    for r in src.execute(sql):
        yield {
            "kind": "message", "ref": f"mr:{r['id']}",
            "ts": _ts_from(r["started_label"] or r["captured_at"]),
            "direction": None, "counterparty": r["contact_name"],
            "address": r["phone_number"], "subject": "thread snippet",
            "text": r["snippet"], "source_table": "dialpad_ui_message_row",
        }


def rows_history(src: sqlite3.Connection):
    sql = """SELECT row_key, started_label, contact_name, phone_number, snippet,
                    activity_type, activity_status, activity_direction
             FROM dialpad_ui_history_row
             WHERE snippet IS NOT NULL AND TRIM(snippet) <> ''"""
    for r in src.execute(sql):
        yield {
            "kind": "history", "ref": r["row_key"],
            "ts": _ts_from(r["started_label"]),
            "direction": r["activity_direction"],
            "counterparty": r["contact_name"], "address": r["phone_number"],
            "subject": f"{r['activity_type'] or ''}/{r['activity_status'] or ''}",
            "text": r["snippet"], "source_table": "dialpad_ui_history_row",
        }


def rows_call_log(src: sqlite3.Connection):
    if not _has_table(src, "call_log"):
        return
    cols = [r[1] for r in src.execute('PRAGMA table_info("call_log")')]
    if "notes" not in cols and "summary" not in cols:
        return
    pick = [c for c in ("id", "created_at", "direction", "from_number", "to_number",
                        "contact_name", "notes", "summary", "duration_seconds")
            if c in cols]
    sel = ", ".join(f'"{c}"' for c in pick)
    for r in src.execute(f"SELECT {sel} FROM call_log"):
        vals = {c: r[c] for c in pick}
        text = (vals.get("notes") or vals.get("summary") or "").strip()
        if not text:
            continue
        yield {
            "kind": "call", "ref": f"cl:{vals.get('id')}",
            "ts": _ts_from(vals.get("created_at")),
            "direction": vals.get("direction"),
            "counterparty": vals.get("contact_name"),
            "address": vals.get("from_number") or vals.get("to_number"),
            "subject": "call_log", "text": text,
            "source_table": "call_log",
        }


def rows_sms_log(src: sqlite3.Connection):
    if not _has_table(src, "sms_log"):
        return
    cols = [r[1] for r in src.execute('PRAGMA table_info("sms_log")')]
    body = next((c for c in ("body", "body_text", "message", "text")
                 if c in cols), None)
    if not body:
        return
    pick = [c for c in ("id", "created_at", "direction", "from_number",
                        "to_number", "contact_name", body) if c in cols]
    sel = ", ".join(f'"{c}"' for c in pick)
    for r in src.execute(f"SELECT {sel} FROM sms_log"):
        vals = {c: r[c] for c in pick}
        text = (vals.get(body) or "").strip()
        if not text:
            continue
        yield {
            "kind": "sms", "ref": f"sl:{vals.get('id')}",
            "ts": _ts_from(vals.get("created_at")),
            "direction": vals.get("direction"),
            "counterparty": vals.get("contact_name"),
            "address": vals.get("from_number") or vals.get("to_number"),
            "subject": "sms_log", "text": text, "source_table": "sms_log",
        }


def rows_voice_transcripts(src: sqlite3.Connection):
    if not _has_table(src, "voice_transcripts"):
        return
    cols = [r[1] for r in src.execute('PRAGMA table_info("voice_transcripts")')]
    body = next((c for c in ("transcript", "text", "content") if c in cols), None)
    if not body:
        return
    pick = [c for c in ("id", "created_at", "recording_id", "phone_number",
                        "direction", body) if c in cols]
    sel = ", ".join(f'"{c}"' for c in pick)
    for r in src.execute(f"SELECT {sel} FROM voice_transcripts"):
        vals = {c: r[c] for c in pick}
        text = (vals.get(body) or "").strip()
        if not text:
            continue
        yield {
            "kind": "voicemail", "ref": f"vt:{vals.get('id')}",
            "ts": _ts_from(vals.get("created_at")),
            "direction": vals.get("direction"), "counterparty": None,
            "address": vals.get("phone_number"), "subject": "voice_transcript",
            "text": text, "source_table": "voice_transcripts",
        }


EXTRACTORS = (
    ("sms", rows_sms),
    ("call", rows_calls),
    ("transcript", rows_transcripts),
    ("voicemail", rows_voicemails),
    ("message_body", rows_message_bodies),
    ("message", rows_messages),
    ("history", rows_history),
    ("call_log", rows_call_log),
    ("sms_log", rows_sms_log),
    ("voice_transcript", rows_voice_transcripts),
)


def do_index(con: sqlite3.Connection, source: str, verbose: bool = False) -> dict:
    t0 = time.time()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    src.row_factory = sqlite3.Row
    con.execute("DELETE FROM comms")
    con.execute("DELETE FROM comms_fts")
    con.execute("DELETE FROM comms_tri")

    counts: dict[str, int] = {}
    total = 0
    for label, fn in EXTRACTORS:
        n = 0
        try:
            for rec in fn(src):
                text = rec.get("text")
                if not text or not str(text).strip():
                    continue
                text = str(text).strip()[:100_000]
                ts = rec.get("ts")
                cur = con.execute(
                    "INSERT OR REPLACE INTO comms(kind, ref, ts, day, direction,"
                    " counterparty, address, subject, text, source_table) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (rec["kind"], rec.get("ref"), ts, _day(ts),
                     rec.get("direction"), rec.get("counterparty"),
                     rec.get("address"), rec.get("subject"), text,
                     rec.get("source_table")))
                rid = cur.lastrowid
                con.execute("INSERT INTO comms_fts(rowid, text, counterparty, kind, id)"
                            " VALUES(?,?,?,?,?)",
                            (rid, text, rec.get("counterparty"), rec["kind"], rid))
                con.execute("INSERT INTO comms_tri(rowid, text, counterparty, kind)"
                            " VALUES(?,?,?,?)",
                            (rid, text, rec.get("counterparty"), rec["kind"]))
                n += 1
                total += 1
                if n % 2000 == 0:
                    con.commit()
                    if verbose:
                        print(f"    {label}: {n:,}", flush=True)
        except sqlite3.Error as exc:
            print(f"  ! {label}: {exc}")
        counts[label] = n
        con.commit()
    src.close()

    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('last_index',?)",
                (dt.datetime.now(dt.timezone.utc).isoformat(),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('schema_version',?)",
                (str(SCHEMA_VERSION),))
    con.execute("INSERT OR REPLACE INTO meta(key,value) VALUES('source',?)", (source,))
    con.commit()
    for t in ("comms_fts", "comms_tri"):
        try:
            con.execute(f"INSERT INTO {t}({t}) VALUES('optimize')")
            con.commit()
        except sqlite3.Error:
            pass
    return {"counts": counts, "total": total,
            "seconds": round(time.time() - t0, 1)}


def do_search(con, term, kind, limit, exact):
    table = "comms_tri" if exact else "comms_fts"
    match = f'"{term}"' if exact else term
    sql = (f"SELECT c.* FROM {table} f JOIN comms c ON c.id = f.rowid "
           f"WHERE {table} MATCH ?")
    args: list = [match]
    if kind:
        sql += " AND c.kind = ?"
        args.append(kind)
    sql += " ORDER BY c.ts DESC LIMIT ?" if kind is None else " LIMIT ?"
    args.append(limit)
    return con.execute(sql, args).fetchall()


def do_stats(con):
    rows = con.execute("SELECT kind, COUNT(*) n, MIN(day) a, MAX(day) b "
                       "FROM comms GROUP BY kind ORDER BY n DESC").fetchall()
    total = con.execute("SELECT COUNT(*) FROM comms").fetchone()[0]
    meta = {r[0]: r[1] for r in con.execute("SELECT key,value FROM meta")}
    return rows, total, meta


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--source", default=DEFAULT_SOURCE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("index")
    p.add_argument("--verbose", action="store_true")
    p = sub.add_parser("search")
    p.add_argument("term")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--exact", action="store_true")
    p = sub.add_parser("timeline")
    p.add_argument("--kind", default=None)
    p.add_argument("--limit", type=int, default=30)
    sub.add_parser("stats")
    a = ap.parse_args()

    con = connect(a.db)
    if a.cmd == "index":
        r = do_index(con, a.source, a.verbose)
        for k, n in r["counts"].items():
            print(f"  {k:<18} {n:>9,}")
        print(f"  {'TOTAL':<18} {r['total']:>9,}  in {r['seconds']}s")
    elif a.cmd == "search":
        for c in do_search(con, a.term, a.kind, a.limit, a.exact):
            when = c["day"] or "?"
            who = " ".join(str(c["counterparty"] or c["address"] or "").split())[:28]
            body = " ".join((c["text"] or "").split())[:150]
            print(f"  [{c['kind']:<9}] {when} {who:<28} {body}")
        print("  (ask with --kind sms|call|voicemail|message|history)")
    elif a.cmd == "timeline":
        sql = "SELECT * FROM comms"
        args = []
        if a.kind:
            sql += " WHERE kind = ?"
            args.append(a.kind)
        sql += " ORDER BY ts DESC LIMIT ?"
        args.append(a.limit)
        for c in con.execute(sql, args):
            who = " ".join(str(c["counterparty"] or c["address"] or "").split())[:26]
            body = " ".join((c["text"] or "").split())[:110]
            print(f"  {c['day'] or '?'} [{c['kind']:<9}] {who:<27} {body}")
    else:
        rows, total, meta = do_stats(con)
        print(f"total communications indexed: {total:,}")
        for r in rows:
            print(f"  {r['kind']:<10} {r['n']:>9,}   {r['a'] or '?'} .. {r['b'] or '?'}")
        print(f"last index: {meta.get('last_index')}   source: {meta.get('source')}")
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
