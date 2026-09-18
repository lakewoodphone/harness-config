#!/usr/bin/env python3
"""FLAG SOURCE: an owner-decision row that has been pending for a week.

THE SIGNAL
----------
`owner_decision_queue WHERE status='pending' AND asked_at < now - 7 days`
in ~/personal-secretary-mvp/data/secretary.db.

WHY THIS IS ABNORMAL, AND WHY THE THRESHOLD IS 7 DAYS
-----------------------------------------------------
A pending row is the OWNER's decision. That is exactly why this source is
narrow: the queue is not agent work, and a source that fired on it would spend
sessions on questions that only a human can answer. So the question a wake has
to answer is not "is this pending" but "has this been pending so long that
something is wrong".

Measured on secratary, 2026-09-18 03:25 UTC, over all 18 rows the queue has ever
answered (`asked_at` -> `answered_at`):

    lag, hours: 0.10, 0.35, 0.52, 0.53, 0.53, 0.74, 0.77, 1.01, 1.14, 2.27,
                4.36, 9.34, 14.84, 17.68, 18.59, 20.10, 22.49, 57.31
    median 1.70 h, mean 9.59 h, worst 57.31 h

The owner's own worst case is under two and a half days. SEVEN DAYS (168 h) is
2.9x his worst observed lag and 99x his median, so a row that old is not "he has
not got to it yet" -- it is one of exactly three things, and only the session can
tell which:
  (a) it is an engineering fault that was mis-filed as a decision for him, and
      it should be fixed rather than asked;
  (b) it is a question that has since become moot or been answered elsewhere,
      and it should be closed with evidence;
  (c) it is genuinely his, in which case it is recorded and left alone.
Only (a) and (b) are worth a session, and finding out which costs one session
per row ONCE -- see SUBJECT below.

PRIORITY  normal. Nothing is on fire; something is stuck.

SUBJECT  odq-stale:<id of the oldest stale row>
    Keyed to a row IDENTITY, not to the day, so dedup makes it fire exactly once
    per stale row: while a wake row for that id lives, refiling is a no-op, and
    once the row is resolved the next-oldest id becomes the key and gets its own
    single session. Combined with a 30-day cooldown (below) the worst case for a
    row that really is his is one triage session a month, not one a day.

MUST NEVER
    - fire while every pending row is younger than the threshold (healthy case)
    - resolve, dismiss or answer a row that is genuinely the owner's decision --
      that hides his question from him, which is worse than the nag
    - treat a pending row as agent work on the strength of its age alone

RUN
    python3 sources/decision-queue-stale.py [--dry-run]
    ODQ_STALE_DAYS=7              age that makes a pending row abnormal
    ODQ_STALE_COOLDOWN_SEC=2592000  re-file floor after a release (30 days)
    OWNER_QUEUE_DB                the app database (default the mvp path)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "decision-queue-stale"
LIST_MAX = 25


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def collect(args) -> list[Finding]:
    days = _float_env("ODQ_STALE_DAYS", 7.0)
    now = _flag.now_utc()
    cutoff = now - timedelta(days=days)

    conn = _flag.ro_connect(_flag.app_db())
    try:
        if not _flag.table_exists(conn, "owner_decision_queue"):
            raise Unreadable(
                f"no owner_decision_queue table in {_flag.app_db()}")
        rows = conn.execute(
            "SELECT id, asked_at, severity, source, blocks, question,"
            "       recommendation, context"
            "  FROM owner_decision_queue"
            " WHERE status='pending' ORDER BY asked_at ASC LIMIT ?",
            (LIST_MAX,)).fetchall()
        pending_total = conn.execute(
            "SELECT COUNT(*) FROM owner_decision_queue WHERE status='pending'"
        ).fetchone()[0]
    finally:
        conn.close()

    stale = []
    for row in rows:
        asked = _flag.parse_dt(row["asked_at"])
        if asked is None or asked >= cutoff:
            continue
        stale.append((row, asked))
    if not stale:
        return []

    anchor = stale[0][0]
    return [_finding(anchor, stale, quiet_count=len(rows), pending_total=pending_total,
                     days=days, now=now)]


def _finding(anchor, stale, quiet_count, pending_total, days, now) -> Finding:
    lines = [
        f"{len(stale)} row(s) in the owner decision queue have been `pending` for "
        f"more than {days:g} days (as of {now.strftime('%Y-%m-%dT%H:%M:%SZ')}; "
        f"{pending_total} pending in total).",
        "",
        "The owner's measured response lag over the 18 rows the queue has ever "
        "answered is a median of 1.7 hours and a worst case of 57.3 hours "
        "(measured 2026-09-18), so a row still pending after a week is not simply "
        "unanswered, and the three possibilities need telling apart:",
        "  (a) an engineering fault mis-filed as a decision for him -- fix it;",
        "  (b) a question that is now moot or was answered elsewhere -- close it with",
        "      the evidence;",
        "  (c) genuinely his -- leave it EXACTLY as it is.",
        "",
        "The rows:",
    ]
    for row, asked in stale:
        age = (now - asked).total_seconds() / 86400
        blocks = (row["blocks"] or "").strip() or "(no blocks field)"
        lines += [
            f"  #{row['id']}  [{row['severity']}]  asked {asked.strftime('%Y-%m-%d %H:%M')}Z"
            f"  ({age:.1f}d)",
            f"      Q: {(row['question'] or '').strip()[:300]}",
            f"      blocks: {blocks[:200]}",
            f"      my recommendation then: {(row['recommendation'] or '-').strip()[:200]}",
        ]
    lines += [
        "",
        "WHAT TO DO",
        "1. Read each row properly, with its context:",
        "     python3 ~/bin/owner-queue.py next --peek 25",
        f"     python3 ~/bin/owner-queue.py --db {_flag.app_db()} list",
        "2. For each row, decide (a), (b) or (c) and act:",
        "   (a) Fix the thing. Then close the row as the work you did, not as an",
        "       answer to him:",
        "         python3 ~/bin/owner-queue.py resolve <id> --how 'was an engineering"
        " fault, not a decision; fixed in <what>'",
        "   (b) Close it with the evidence that makes it moot:",
        "         python3 ~/bin/owner-queue.py resolve <id> --how '<what superseded it>'",
        "   (c) LEAVE IT PENDING. Do not 'answer' it on his behalf and do not resolve",
        "       it. State in your report why it is genuinely his.",
        "3. If a row is his but is now blocking work that could go around it, say so",
        "   in one line — do not refile a new question.",
        "",
        "DO NOT: invent an answer for the owner; use `answer` on his behalf; dismiss",
        "a row to make the queue look clean; or edit rows directly in SQL. The queue",
        "is the single source of truth for what needs him and it must stay honest.",
        "",
        "Report at the end: for each row, (a)/(b)/(c), what you did, and the evidence.",
    ]
    return Finding(
        subject=f"odq-stale:{anchor['id']}",
        prompt="\n".join(lines),
        context=(f"{SOURCE}: {len(stale)} pending row(s) older than {days:g}d; "
                 f"anchor row #{anchor['id']} asked {anchor['asked_at']}"),
        priority="normal",
        kind="triage",
        cooldown_seconds=int(os.environ.get("ODQ_STALE_COOLDOWN_SEC") or 2592000),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
