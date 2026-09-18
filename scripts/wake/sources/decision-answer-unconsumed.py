#!/usr/bin/env python3
"""FLAG SOURCE: a decision was MADE and the work it ordered was never done.

THE SIGNAL
----------
`owner_decision_queue WHERE status='answered' AND resolved_at IS NULL
 AND answered_at < now - 6 hours`
in ~/personal-secretary-mvp/data/secretary.db.

This is the opposite of decision-queue-stale.py. That one refuses to treat a
pending row as agent work, because a pending row is the owner's decision. This one
is about a row the queue has already recorded an outcome for: the `answer` column
holds what was decided, and `resolved_at IS NULL` means nothing ever closed it.

WHY THIS IS ABNORMAL, AND WHY THE THRESHOLD IS 6 HOURS
------------------------------------------------------
Measured on secratary, 2026-09-18 03:25 UTC:

    8 rows have status='answered'
    2 of them (ids 60, 71) have resolved_at EQUAL TO answered_at, to the second
    6 have resolved_at IS NULL, at 52.3, 52.3, 50.7, 50.1, 9.1 and 1.3 hours
      since the answer -- and their answer text orders real work:
        #64 "Let the Sep 16 run stand. Dismiss him in Gusto ..."
        #69 "A: keep the ring window as it is and fix only the spoken message."
        #80 "ACCEPT the brace-and-through-bolt retrofit with the 40 mph rule."
        #91 "Total set at 460 USD ... tell the customer straight that it does
             not make sense"

So the healthy resting state for an answered row is CLOSED, and closing costs no
extra time at all (measured lag: zero seconds, on the two rows that did it). The
threshold is 6 hours, which is longer than the longest plausible single session
that would decide a row and then do the work it ordered -- beyond that, nobody is
working on it. The zero-second figure is only n=2 and that is thin evidence, which
is exactly why the threshold is generous rather than tight.

NOTHING SURFACES THIS STATE. Verified by reading, 2026-09-18:
  - owner-queue.py `list` and `next` both select `WHERE status='pending'`;
  - journal.py's mirror is generated from pending only and is titled
    "OWNER QUESTIONS -- open only" (15 pending of 108 rows);
  - `grep -rln owner_decision_queue` over harness-config, the app's scripts/, the
    app tree and ceo-kernel finds no reader of `status='answered'`. The only
    writer is owner-queue.py itself.
A decision that was made and not executed is therefore invisible everywhere.

PRIORITY  high. The loop was closed on paper and left open in the world.

SUBJECT  odq-answer-open:<id of the OLDEST unconsumed answer>
    Keyed to a row identity so dedup fires it exactly once per unconsumed answer;
    once that row is closed, the next-oldest becomes the key. One session cleans
    the set, and the 30-day cooldown bounds what happens if it does not.

MUST NEVER
    - fire when every answered row is resolved (the healthy case)
    - re-do work that was already done: the session must VERIFY first
    - contact any customer. If the recorded answer requires customer contact, the
      session records what should be said and hands it to the owner -- outbound
      needs his explicit per-message instruction, always
    - treat a row as unexecuted merely because it is old

RUN
    python3 sources/decision-answer-unconsumed.py [--dry-run]
    ODQ_ANSWER_HOURS=6              age that makes an answer abnormal
    ODQ_ANSWER_COOLDOWN_SEC=2592000 re-file floor after a release (30 days)
    OWNER_QUEUE_DB                  the app database (default the mvp path)
"""
from __future__ import annotations

import os
import sys
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import _flag                                                     # noqa: E402
from _flag import Finding, Unreadable                            # noqa: E402

SOURCE = "decision-answer-unconsumed"
LIST_MAX = 25


def _float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name) or default)
    except ValueError:
        return default


def collect(args) -> list[Finding]:
    hours = _float_env("ODQ_ANSWER_HOURS", 6.0)
    now = _flag.now_utc()
    cutoff = now - timedelta(hours=hours)

    conn = _flag.ro_connect(_flag.app_db())
    try:
        if not _flag.table_exists(conn, "owner_decision_queue"):
            raise Unreadable(
                f"no owner_decision_queue table in {_flag.app_db()}")
        rows = conn.execute(
            "SELECT id, asked_at, answered_at, severity, blocks, question,"
            "       answer, recommendation"
            "  FROM owner_decision_queue"
            " WHERE status='answered' AND resolved_at IS NULL"
            "   AND answered_at IS NOT NULL"
            " ORDER BY answered_at ASC LIMIT ?",
            (LIST_MAX,)).fetchall()
    finally:
        conn.close()

    stale = []
    for row in rows:
        answered = _flag.parse_dt(row["answered_at"])
        if answered is None or answered >= cutoff:
            continue
        stale.append((row, answered))
    if not stale:
        return []

    anchor = stale[0]
    return [_finding(anchor, stale, hours=hours, now=now)]


def _finding(anchor, stale, hours, now) -> Finding:
    anchor_row, anchor_at = anchor
    lines = [
        f"{len(stale)} row(s) in the owner decision queue carry a recorded answer "
        f"and were never resolved for more than {hours:g} hour(s) as of "
        f"{now.strftime('%Y-%m-%dT%H:%M:%SZ')}. `resolved_at IS NULL` means nothing "
        f"closed them, and this state is invisible to every existing view: both "
        f"`owner-queue.py list` and `next` select status='pending', and the journal "
        f"mirror is generated from pending only.",
        "",
        f"Oldest: #{anchor_row['id']}, answered "
        f"{anchor_at.strftime('%Y-%m-%d %H:%M')}Z "
        f"({(now - anchor_at).total_seconds() / 3600:.1f}h ago).",
        "",
        "The rows:",
    ]
    for row, answered in stale:
        age = (now - answered).total_seconds() / 3600
        lines += [
            f"  #{row['id']}  [{row['severity']}]  answered "
            f"{answered.strftime('%Y-%m-%d %H:%M')}Z  ({age:.1f}h)",
            f"      Q: {(row['question'] or '').strip()[:220]}",
            f"      ANSWER: {(row['answer'] or '').strip()[:400]}",
            f"      blocks: {((row['blocks'] or '').strip() or '(none)')[:160]}",
        ]
    lines += [
        "",
        "WHAT TO DO",
        "Work the rows oldest first, and for EACH one determine which it is:",
        "  (i)  the action was already done and only the row was left open -> verify",
        "       it (read the artifact, the case file, the git log, the vendor system)",
        "       and close it:",
        "         python3 ~/bin/owner-queue.py resolve <id> --how '<what you verified,",
        "         and where you verified it>'",
        "  (ii) the action was NOT done and is agent work -> do it, then resolve it the",
        "       same way, naming the evidence.",
        "  (iii) the action needs the owner or a customer -> DO NOT contact anyone.",
        "       Write what should be said and to whom, leave the row for him, and say",
        "       so in your report.",
        "",
        "VERIFY BEFORE YOU ACT. The answer text was written hours or days ago; the",
        "world may have moved, and re-doing a finished action (dismissing someone",
        "twice, promising a customer the same thing twice) is worse than doing",
        "nothing. If you cannot tell whether it was done, say so and leave the row.",
        "",
        "DO NOT: phone, text or email any customer or vendor -- outbound contact needs",
        "the owner's explicit per-message instruction, without exception; use",
        "`answer` on a row; or resolve a row you did not actually verify.",
        "",
        "Report: per row, (i)/(ii)/(iii), what you verified and where, what you did,",
        "and the one-line reason for anything you left open.",
    ]
    return Finding(
        subject=f"odq-answer-open:{anchor_row['id']}",
        prompt="\n".join(lines),
        context=(f"{SOURCE}: {len(stale)} answered-but-unresolved row(s) older than "
                 f"{hours:g}h; anchor #{anchor_row['id']} answered "
                 f"{anchor_row['answered_at']}"),
        priority="high",
        kind="triage",
        cooldown_seconds=int(os.environ.get("ODQ_ANSWER_COOLDOWN_SEC") or 2592000),
    )


if __name__ == "__main__":
    sys.exit(_flag.run(SOURCE, collect))
