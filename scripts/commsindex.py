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

COMPLETENESS (2026-09-14, after measuring the built artefact). Three defects were
found by comparing the index against its source, not by reading this file:

  * `dialpad_ui_history_row.row_key` is NOT unique (10,703 rows, 4,746 distinct
    keys, 145 of them with different text). Keying the index on `row_key` silently
    dropped 5,716 re-captures -- correct -- but also 215 rows of text that existed
    nowhere else. Refs are now a hash of (row_key, text), so re-captures collapse
    and distinct rows survive.
  * 1,192 voicemails have a recording but no transcript, and were skipped entirely,
    so "who left a voicemail in July" was unanswerable. They are now indexed with a
    synthetic body that still carries the number, the date and the recording id.
  * `dialpad_sms_cache` holds 2,744 genuinely duplicated rows (the webhook path and
    the thread-crawler path both store the same message id, byte-identical bodies).
    Collapsing them is right -- but it must be *reported*, so silent loss and
    deliberate de-duplication cannot look the same. `index` now prints written vs
    kept per source.

Verify with `comms-coverage.py`, which derives its expectations from the extractors
below rather than re-implementing them, so the audit cannot drift from the indexer.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import os
import re
import sqlite3
import sys
import time

SCHEMA_VERSION = 2

# How old the index may be before `stats` calls it stale. The index is rebuilt by
# comms-refresh.py on a 30-minute cadence on the authority (just after the Dialpad
# harvest), so an hour means the refresh has stopped running.
STALE_HOURS = 1.0

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

-- The FTS tables are DROPPED and rebuilt on every index run (see do_index). A bare
-- `DELETE FROM` does not remove FTS5 shadow rows, so repeated `INSERT` under a
-- reused rowid left 9,693 stale duplicates in the previous build -- search returned
-- the same message twice and could match text that had been replaced.
CREATE VIRTUAL TABLE IF NOT EXISTS comms_fts USING fts5(
    text, counterparty UNINDEXED, kind UNINDEXED, id UNINDEXED, address,
    tokenize='porter unicode61');
CREATE VIRTUAL TABLE IF NOT EXISTS comms_tri USING fts5(
    text, counterparty, kind UNINDEXED, address,
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


def _ref_hash(*parts: object) -> str:
    """A short, stable ref for sources whose natural key is not unique.

    `dialpad_ui_history_row.row_key` repeats -- the crawler captures the same row
    many times -- so a ref must be derived from the row's *content*, not its key:
    identical re-captures collapse, rows with different text all survive.
    """
    raw = "\u0001".join("" if p is None else str(p) for p in parts)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


# ── Dialpad transcript artifacts ──────────────────────────────────────────────
#
# Dialpad interleaves its own AI analytics labels into the transcript stream as
# standalone `speaker: label` lines. Measured over the whole corpus on 2026-09-14:
# 5,710 transcripts, 148,419 lines, and **38.6% of those lines are labels** --
# 57,221 of them, from a closed vocabulary of 30 tokens (`question`, `ner`,
# `whole_call_summary`, `action_item_v2`, `ai_csat_reboot_ineligible`, ...).
#
# They matter twice: they fragment phrase searches (`"whole call summary"` matched
# a label instead of a conversation) and they make every call result read as noise.
# Dialogue that happens to be a single lowercase word lives in the other 61.4%:
# every payload-only line that is real speech is capitalised and punctuated
# ('Oh.', 'No.', 'Hi.'), so a lowercase-token rule provably does not touch it --
# of the 57,221 lines this drops, exactly 2 payloads were seen fewer than 3 times
# across the corpus, and both are labels too (`case_number`, `postcode`).
_ARTIFACT_LINE = re.compile(r"^\s*(?P<speaker>[^:\n]{0,60}):\s*(?P<payload>[a-z][a-z0-9_]{2,40})\s*$")

# Kept explicit so the rule can be read and argued with, not inferred.
_ARTIFACT_LABELS = frozenset({
    "question", "ner", "ai_csat_reboot_ineligible", "whole_call_summary",
    "call_purpose_category", "whole_call_summary_fragment", "action_item_v2",
    "monologuing", "currency", "call_purpose", "time", "positive_sentiment",
    "speaking_too_quickly", "action_item", "address", "voicemail",
    "negative_sentiment", "phone_number", "contact_name", "swearing",
    "email_address", "date", "contact_company", "insight_chapter",
    "account_number", "insight_qa_pair", "insight_decision_made", "pii",
    "case_number", "postcode",
})


def strip_dialpad_artifacts(text: str | None) -> str:
    """Remove Dialpad's analytics-label lines from a transcript."""
    if not text:
        return ""
    kept = []
    for line in text.splitlines():
        if not line.strip():
            continue
        m = _ARTIFACT_LINE.match(line)
        if m and m.group("payload") in _ARTIFACT_LABELS:
            continue
        kept.append(line.strip())
    return "\n".join(kept)


def _clean_retranscripts(src: sqlite3.Connection) -> dict:
    """call_id -> the newest genuinely clean Whisper transcript, when one exists.

    `dialpad_call_transcript` text is a machine transcript with the label noise
    stripped; a re-transcript of the recording is real audio transcribed again, so
    where both exist the re-transcript is the better document to search.
    """
    out: dict[str, str] = {}
    if not _has_table(src, "dialpad_call_retranscript"):
        return out
    sql = """SELECT r.call_id, r.transcript_text
             FROM dialpad_call_retranscript r
             JOIN (SELECT call_id, MAX(updated_at) mx FROM dialpad_call_retranscript
                   WHERE status='success' GROUP BY call_id) newest
               ON newest.call_id = r.call_id AND newest.mx = r.updated_at
             WHERE r.status='success'"""
    try:
        for r in src.execute(sql):
            text = (r["transcript_text"] or "").strip()
            if text:
                out[str(r["call_id"])] = text
    except sqlite3.Error:
        return {}
    return out


def _webhook_transcripts(src: sqlite3.Connection) -> dict:
    """call_id -> transcript/recap text delivered by the Dialpad webhook.

    `dialpad_transcript_cache` holds 4,096 calls and, measured 2026-09-14, every one
    of them also exists in `dialpad_call_full`. 646 of its transcripts duplicate a
    call record that already has better text, and only 45 carry text that
    `dialpad_call_full` lacks -- so the whole table is a *fallback* source, and
    indexing it as a peer is what made two copies of the same call appear in search
    results. It is folded into the call row here and the extractor is guarded.
    """
    out: dict[str, str] = {}
    if not _has_table(src, "dialpad_transcript_cache"):
        return out
    try:
        for r in src.execute(
                "SELECT call_id, transcript_text, recap_text FROM dialpad_transcript_cache"):
            t = strip_dialpad_artifacts(r["transcript_text"])
            c = strip_dialpad_artifacts(r["recap_text"])
            if t or c:
                out[str(r["call_id"])] = t + (f"\n\nRECAP: {c}" if c else "")
    except sqlite3.Error:
        return {}
    return out


def _dedup_key(rec: dict) -> str:
    """The identity of a communication, used to collapse two records of one event.

    Dialpad writes a call as **two** call rows -- two legs, one of which carries the
    recording -- with the same caller, the same day and byte-identical transcripts.
    Measured 2026-09-14: 2,425 such groups covering 2,433 redundant rows, which is
    why a search for "battery" returned every conversation twice.

    SMS and messages keep their own id as the key (their ids are reliable, and two
    identical texts at different times are genuinely two messages). Calls and
    voicemails fall back to (party, day, text) -- with a 40-character floor, because
    a two-word transcript like "Yeah." is not distinctive enough to merge on.
    """
    ref = str(rec.get("ref"))
    text = str(rec.get("text") or "")
    day = _day(rec.get("ts")) or ""
    # Without a date a "same party, same text" match is not evidence of the same
    # event -- it merged 2,525 voicemails into 371 before this guard existed, because
    # the crawler's relative labels ("4 days ago") had already cost those rows their
    # timestamps. No date, no semantic merge.
    if (rec.get("kind") in ("call", "voicemail") and day
            and len(text) >= 40 and not text.startswith("[")):
        dig = re.sub(r"\D", "", str(rec.get("address") or ""))
        return (f"{rec.get('kind')}::{dig[-10:]}::{day}::"
                f"{hashlib.sha1(text.encode('utf-8')).hexdigest()[:16]}")
    return ref


def _richness(rec: dict) -> tuple:
    """Which of two records describing one event to keep: real words over markers."""
    text = str(rec.get("text") or "")
    return (0 if text.startswith("[") else 1, len(text), rec.get("ts") or 0)


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
    clean = _clean_retranscripts(src)
    webhook = _webhook_transcripts(src)
    for r in src.execute(sql):
        text = strip_dialpad_artifacts(r["transcription_text"])
        # A re-transcript of the recording beats Dialpad's own text when we have one.
        text = clean.get(str(r["call_id"])) or text or webhook.get(str(r["call_id"]), "")
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
    """Webhook-delivered transcripts, only for calls the harvest has not recorded.

    Guarded with NOT EXISTS on `dialpad_call_full` because otherwise this extractor
    and `rows_calls` both describe the same call and search returns it twice. When
    the harvest has a record, `rows_calls` already carries the best available text
    (re-transcript, then Dialpad's, then this table's).
    """
    sql = """SELECT t.call_id, t.started_at, t.direction, t.phone_normalized,
                    t.transcript_text, t.recap_text, t.has_transcript, t.has_recap
             FROM dialpad_transcript_cache t
             WHERE NOT EXISTS (SELECT 1 FROM dialpad_call_full c
                               WHERE c.call_id = t.call_id)"""
    for r in src.execute(sql):
        t = strip_dialpad_artifacts(r["transcript_text"])
        c = strip_dialpad_artifacts(r["recap_text"])
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
    """Every voicemail, including the ones Dialpad never transcribed.

    A voicemail without a transcript is still a communication: it has a caller, a
    date and a recording. Skipping those rows made 1,192 of them invisible, so the
    question "did anyone leave a message last week" had no answer in the index.

    `vm_id` is not unique either -- the crawler captured the same voicemail many
    times, sometimes with a transcript and sometimes without -- so the richest
    capture wins in `do_index` rather than letting a later empty re-capture erase
    the transcript.

    TIMESTAMP NOTE. `started_label` is a *relative* label ("4 days ago", "99 days
    ago"), not a date: `_ts_from` cannot parse it, so keying the row on it silently
    left thousands of rows undated *and* made every one of them look like the same
    day to the de-duplication key. `captured_at` is the real timestamp the crawl
    wrote, so that is the date these rows carry.
    """
    sql = """SELECT vm_id, started_label, direction, phone_number, contact_name,
                    transcript, duration_text, recording_id, captured_at
             FROM dialpad_ui_voicemail_row
             ORDER BY (CASE WHEN TRIM(COALESCE(transcript,'')) = '' THEN 0 ELSE 1 END),
                      captured_at"""
    for r in src.execute(sql):
        text = (r["transcript"] or "").strip()
        recording = (r["recording_id"] or "").strip()
        synthetic = not text
        if synthetic:
            bits = ["[voicemail, no transcript]"]
            if r["contact_name"]:
                bits.append(str(r["contact_name"]))
            if r["phone_number"]:
                bits.append(str(r["phone_number"]))
            if r["duration_text"]:
                bits.append(f"duration {r['duration_text']}")
            if recording:
                bits.append(f"recording_id {recording}")
            text = " ".join(bits)
        yield {
            "kind": "voicemail", "ref": str(r["vm_id"]),
            "ts": _ts_from(r["captured_at"]),
            "direction": r["direction"],
            "counterparty": r["contact_name"], "address": r["phone_number"],
            "subject": (r["duration_text"] or r["started_label"] or None)
                       if not synthetic else "no transcript",
            "text": text,
            "source_table": "dialpad_ui_voicemail_row",
        }


def rows_call_voicemails(src: sqlite3.Connection):
    """Voicemails that arrived as *calls*, which is nearly all of them since June.

    The Playwright UI crawl (`dialpad_ui_voicemail_row`) was the only voicemail
    source this system knew about, and it stopped on 2026-06-14 -- so the working
    assumption became "every voicemail since then is missing". It is not true: the
    half-hourly REST harvest has been writing every voicemail as a call the whole
    time, carrying `voicemail_link` (https://dialpad.com/v/<call_id>), a recording
    id, and Dialpad's transcript when it has one. 916 such calls exist, the newest
    from today. They were simply filed as `call`, so "who left a voicemail" could not
    find them by kind.

    Indexed with ref `vc:<call_id>` so they cannot collide with the UI rows, whose
    refs are Dialpad voicemail ids.
    """
    sql = """SELECT call_id, direction, date_started_ms, contact_name, contact_phone,
                    external_number, transcription_text, duration_seconds,
                    voicemail_recording_id, voicemail_link, state
             FROM dialpad_call_full
             WHERE voicemail_link IS NOT NULL AND TRIM(voicemail_link) <> ''"""
    clean = _clean_retranscripts(src)
    webhook = _webhook_transcripts(src)
    # The UI crawl only ever covered 2026-04-24..2026-06-14, so for a call from that
    # window that has no text of its own, a UI voicemail row with a transcript for the
    # same number is the same event described better. Suppressing these removes a
    # duplicated voicemail without ever touching a row that carries its own words --
    # and never a call after the crawl stopped.
    ui_with_text = set()
    if _has_table(src, "dialpad_ui_voicemail_row"):
        for r in src.execute(
                "SELECT phone_number FROM dialpad_ui_voicemail_row "
                "WHERE TRIM(COALESCE(transcript,'')) <> ''"):
            dig = re.sub(r"\D", "", r["phone_number"] or "")
            if dig:
                ui_with_text.add(dig[-10:])
    crawl_window_end_ms = 1_781_600_000_000  # 2026-06-15T00:00Z, day after last crawl
    for r in src.execute(sql):
        text = strip_dialpad_artifacts(r["transcription_text"])
        text = clean.get(str(r["call_id"])) or text or webhook.get(str(r["call_id"]), "")
        recording = (r["voicemail_recording_id"] or "").strip()
        phone = r["contact_phone"] or r["external_number"]
        if not text:
            dig = re.sub(r"\D", "", str(phone or ""))
            if (dig and dig[-10:] in ui_with_text
                    and (r["date_started_ms"] or 0) < crawl_window_end_ms):
                continue  # the UI row for this voicemail has the real transcript
            bits = ["[voicemail, no transcript]"]
            if r["contact_name"]:
                bits.append(str(r["contact_name"]))
            if phone:
                bits.append(str(phone))
            if r["duration_seconds"]:
                bits.append(f"duration {int(r['duration_seconds'])}s")
            if recording:
                bits.append(f"recording_id {recording}")
            text = " ".join(bits)
        yield {
            "kind": "voicemail", "ref": f"vc:{r['call_id']}",
            "ts": _ts_from(r["date_started_ms"]), "direction": r["direction"],
            "counterparty": r["contact_name"],
            "address": r["contact_phone"] or r["external_number"],
            "subject": "voicemail (call record)" if recording else "voicemail",
            "text": text, "source_table": "dialpad_call_full_voicemail",
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
            # captured_at, not the relative label -- see the note in rows_voicemails.
            "ts": _ts_from(r["captured_at"]),
            "direction": None, "counterparty": r["contact_name"],
            "address": r["phone_number"],
            "subject": f"thread snippet ({r['started_label']})" if r["started_label"]
                       else "thread snippet",
            "text": r["snippet"], "source_table": "dialpad_ui_message_row",
        }


def rows_history(src: sqlite3.Connection):
    sql = """SELECT row_key, started_label, contact_name, phone_number, snippet,
                    activity_type, activity_status, activity_direction, captured_at
             FROM dialpad_ui_history_row
             WHERE snippet IS NOT NULL AND TRIM(snippet) <> ''"""
    for r in src.execute(sql):
        yield {
            "kind": "history",
            # row_key repeats; the content hash is what makes the ref unique
            # without losing rows that differ (see the module docstring).
            "ref": "hr:" + _ref_hash(r["row_key"], r["snippet"]),
            # captured_at, not the relative label -- see the note in rows_voicemails.
            "ts": _ts_from(r["captured_at"]),
            "direction": r["activity_direction"],
            "counterparty": r["contact_name"], "address": r["phone_number"],
            "subject": (f"{r['activity_type'] or ''}/{r['activity_status'] or ''}"
                        + (f" ({r['started_label']})" if r["started_label"] else "")),
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
    ("call_voicemail", rows_call_voicemails),
    ("message_body", rows_message_bodies),
    ("message", rows_messages),
    ("history", rows_history),
    ("call_log", rows_call_log),
    ("sms_log", rows_sms_log),
    ("voice_transcript", rows_voice_transcripts),
)

# label -> source table, so `index` can report written vs kept per source and show
# exactly how many rows were collapsed under a shared ref.
_EXTRACTOR_TABLE = {
    "sms": "dialpad_sms_cache",
    "call": "dialpad_call_full",
    "transcript": "dialpad_transcript_cache",
    "voicemail": "dialpad_ui_voicemail_row",
    "call_voicemail": "dialpad_call_full_voicemail",
    "message_body": "dialpad_ui_message_body_row",
    "message": "dialpad_ui_message_row",
    "history": "dialpad_ui_history_row",
    "call_log": "call_log",
    "sms_log": "sms_log",
    "voice_transcript": "voice_transcripts",
}


def do_index(con: sqlite3.Connection, source: str, verbose: bool = False) -> dict:
    t0 = time.time()
    src = sqlite3.connect(f"file:{source}?mode=ro", uri=True, timeout=60)
    src.row_factory = sqlite3.Row
    con.execute("DELETE FROM comms")
    # `DELETE FROM` does NOT purge FTS5 shadow rows: re-inserting under a reused
    # rowid appended a second copy, so the previous index carried 9,693 stale rows
    # and search returned duplicates. Drop and recreate instead -- this is a full
    # rebuild, so there is nothing to preserve.
    for table in ("comms_fts", "comms_tri"):
        con.execute(f"DROP TABLE IF EXISTS {table}")
    con.commit()
    con.executescript(SCHEMA)
    con.commit()

    counts: dict[str, int] = {}
    kept: dict[str, int] = {}
    collapsed: dict[str, int] = {}
    total = 0
    for label, fn in EXTRACTORS:
        # De-duplicate BEFORE inserting, one extractor at a time.
        #
        # The first version streamed rows straight in with INSERT OR REPLACE and
        # relied on the unique index to drop repeats. That is wrong twice over: a
        # replaced row gets a NEW rowid, so the FTS tables kept one entry per *write*
        # (175,885) while `comms` held one per *communication* (166,192) -- 9,693 FTS
        # rows pointing at rowids that no longer existed. Collapsing in Python first
        # means every ref is written exactly once and the three tables agree by
        # construction. Memory is safe because the duplicates are always within one
        # source table, and the largest of those is 127k short SMS bodies.
        by_key: dict[str, dict] = {}
        yielded = 0
        try:
            for rec in fn(src):
                text = rec.get("text")
                if not text or not str(text).strip():
                    continue
                yielded += 1
                ref = rec.get("ref")
                if not ref:
                    # A null ref would collapse every such row into one. Give it a
                    # content-derived ref instead, so nothing is silently merged.
                    ref = "auto:" + _ref_hash(rec.get("text"), rec.get("ts"))
                    rec = dict(rec, ref=ref)
                rec = dict(rec, text=str(text).strip()[:100_000])
                by_key[_dedup_key(rec)] = rec  # richest wins, decided in _richness
            # Two different semantic keys can still carry the same ref (the same
            # voicemail id captured with two different texts). The unique index on
            # (source_table, ref) is what the query layer relies on, so enforce it
            # here rather than discovering it as a constraint failure mid-insert.
            by_ref: dict[str, dict] = {}
            for rec in by_key.values():
                ref = str(rec.get("ref"))
                prev = by_ref.get(ref)
                if prev is None or _richness(rec) > _richness(prev):
                    by_ref[ref] = rec
            for ref, rec in by_ref.items():
                ts = rec.get("ts")
                cur = con.execute(
                    "INSERT INTO comms(kind, ref, ts, day, direction,"
                    " counterparty, address, subject, text, source_table) "
                    "VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (rec["kind"], str(rec.get("ref") or ref), ts, _day(ts),
                     rec.get("direction"), rec.get("counterparty"),
                     rec.get("address"), rec.get("subject"), rec["text"],
                     rec.get("source_table")))
                rid = cur.lastrowid
                con.execute(
                    "INSERT INTO comms_fts(rowid, text, counterparty, kind, id, address)"
                    " VALUES(?,?,?,?,?,?)",
                    (rid, rec["text"], rec.get("counterparty"), rec["kind"], rid,
                     rec.get("address")))
                con.execute(
                    "INSERT INTO comms_tri(rowid, text, counterparty, kind, address)"
                    " VALUES(?,?,?,?,?)",
                    (rid, rec["text"], rec.get("counterparty"), rec["kind"],
                     rec.get("address")))
                total += 1
            con.commit()
            if verbose:
                print(f"    {label}: {total:,} total", flush=True)
        except sqlite3.Error as exc:
            print(f"  ! {label}: {exc}")
        counts[label] = yielded
        collapsed[label] = yielded - len(by_ref)
        con.commit()
        table = _EXTRACTOR_TABLE.get(label)
        if table:
            kept[label] = con.execute(
                "SELECT COUNT(*) FROM comms WHERE source_table = ?", (table,)
            ).fetchone()[0]
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
    # The three tables must agree by construction. If they do not, everything this
    # index says about its own completeness is worthless -- so measure, do not trust.
    real = con.execute("SELECT COUNT(*) FROM comms").fetchone()[0]
    fts = con.execute(f"SELECT COUNT(*) FROM comms_fts").fetchone()[0]
    tri = con.execute(f"SELECT COUNT(*) FROM comms_tri").fetchone()[0]
    return {"counts": counts, "kept": kept, "collapsed": collapsed, "total": total,
            "kept_total": real, "fts_rows": fts, "trigram_rows": tri,
            "consistent": real == fts == tri,
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


def index_age_seconds(meta: dict) -> float | None:
    """Seconds since the last successful index, or None if it never ran."""
    last = meta.get("last_index")
    if not last:
        return None
    try:
        when = dt.datetime.fromisoformat(last)
    except ValueError:
        return None
    if when.tzinfo is None:
        when = when.replace(tzinfo=dt.timezone.utc)
    return (dt.datetime.now(dt.timezone.utc) - when).total_seconds()


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
        collapsed_total = 0
        for k, n in r["counts"].items():
            collapsed = r["collapsed"].get(k, 0)
            collapsed_total += collapsed
            note = f"   ({collapsed:,} collapsed as duplicates)" if collapsed else ""
            print(f"  {k:<18} {n:>9,} yielded{note}")
        verdict = ("OK" if r["consistent"] else
                   f"MISMATCH comms={r['kept_total']:,} fts={r['fts_rows']:,} "
                   f"tri={r['trigram_rows']:,}")
        print(f"  {'TOTAL':<18} {r['total']:>9,} indexed "
              f"({collapsed_total:,} duplicate refs collapsed) in {r['seconds']}s"
              f"   consistency: {verdict}")
        return 0 if r["consistent"] else 1
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
        age = index_age_seconds(meta)
        print(f"total communications indexed: {total:,}")
        for r in rows:
            print(f"  {r['kind']:<10} {r['n']:>9,}   {r['a'] or '?'} .. {r['b'] or '?'}")
        if age is None:
            print("last index: NEVER — this index has not been built")
        else:
            hours = age / 3600.0
            flag = "  STALE" if hours > STALE_HOURS else ""
            print(f"last index: {meta.get('last_index')} "
                  f"({hours:.1f}h ago){flag}   source: {meta.get('source')}")
        # FTS/trigram must agree with the base table or the index is lying.
        both = all(
            con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] == total
            for t in ("comms_fts", "comms_tri")
        )
        print(f"consistency: comms={total:,} "
              + "  ".join(f"{t}={con.execute(f'SELECT COUNT(*) FROM {t}').fetchone()[0]:,}"
                          for t in ("comms_fts", "comms_tri"))
              + ("  OK" if both else "  MISMATCH"))
    con.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
