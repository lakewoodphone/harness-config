"""Give agent_questions a shelf life too -- the same rot, one table over.

Measured 2026-09-15 on the authority: `agent_questions` held **313 pending** rows, the
oldest **3226 h (134 days)**, the newest 1405 h (58 days), **nothing created in 30
days**, all `agent_id=orchestrator`. They are SMS-era approval asks ("Ready to send this
SMS to +1848... Mordecai's iPhone 14 repair"), a Gmail re-authorisation ask, and at
least four paraphrase variants of the same Pesach question. Meanwhile the kernel's
attention-debt check counted every one of them as live owner-attention debt and put
"oldest question 134d old" on the owner's badge -- a permanently red line about a
channel nothing has written to in a month.

The table's own CHECK constraint already allows `expired`, so this needs no schema
change beyond a `status_note` (lazy ALTER, the same pattern as owner_message_queue) to
record *why* a row left the pending set. Status change only; nothing is deleted and
`question`/`context` are untouched.

Fourteen days: a question the shop has not answered in a fortnight is no longer the
question it was, and the owner's real decisions live in `owner_decision_queue`, which
is read one at a time. The kernel check is narrowed to match, so the badge stops
counting a dead channel's backlog as live work.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path.home() / "personal-secretary-mvp"
SWEEP = REPO / "app" / "services" / "lifecycle_sweep.py"

BLOCK_ANCHOR = "def _close_expired_drafts(conn, lock) -> int:"

BLOCK = '''# ── Agent question shelf life ────────────────────────────────────────
# Same disease as the owner queue (see the block above): nothing aged this table, so
# 313 pending questions sat 58-134 days while the kernel counted all of them as live
# owner-attention debt and printed "oldest question 134d old" on the owner's badge.
# Measured 2026-09-15: nothing has created a question in 30 days.
AGENT_QUESTION_MAX_AGE_HOURS = 336.0  # 14 days
_AGENT_QUESTION_COLUMNS_ENSURED: set[str] = set()


def _ensure_agent_question_columns(db_url: str, conn) -> None:
    """Add status_note to agent_questions if absent (lazy, idempotent, per db_url)."""
    if db_url in _AGENT_QUESTION_COLUMNS_ENSURED:
        return
    try:
        cols = {row[1] for row in conn.execute("PRAGMA table_info(agent_questions)")}
    except Exception:  # noqa: BLE001 - a missing table is not this phase's problem
        return
    if not cols:
        return
    if "status_note" not in cols:
        conn.execute("ALTER TABLE agent_questions ADD COLUMN status_note TEXT")
        conn.commit()
    _AGENT_QUESTION_COLUMNS_ENSURED.add(db_url)


def _expire_stale_agent_questions(conn, lock, db_url) -> dict[str, int]:
    """Expire pending questions nobody answered in time.

    Reversible in the same sense as the owner queue: the status changes and the reason
    is recorded, the question and its context stay exactly as written.
    """
    counts = {"agent_questions_expired": 0}
    cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=AGENT_QUESTION_MAX_AGE_HOURS)
    ).isoformat()
    try:
        _ensure_agent_question_columns(db_url, conn)
    except Exception as exc:  # noqa: BLE001 - the sweep must survive a bad phase
        log.warning("lifecycle sweep: agent question ageing skipped: %s", exc)
        return counts
    try:
        with lock:
            cur = conn.execute(
                "UPDATE agent_questions SET status = 'expired', status_note = ? "
                "WHERE status = 'pending' AND datetime(created_at) < datetime(?)",
                (
                    "expired: unanswered for more than %d days"
                    % int(AGENT_QUESTION_MAX_AGE_HOURS / 24),
                    cutoff,
                ),
            )
            conn.commit()
            counts["agent_questions_expired"] = int(cur.rowcount or 0)
    except Exception as exc:  # noqa: BLE001 - the sweep must survive a bad phase
        log.warning("lifecycle sweep: agent question ageing failed: %s", exc)
    return counts


'''

SUMMARY_ANCHOR = '        "owner_messages_expired": 0,'
SUMMARY_REPLACE = '''        "owner_messages_expired": 0,
        "agent_questions_expired": 0,'''

PHASE_ANCHOR = "    summary.update(_expire_stale_owner_messages(conn, _db_lock, db_url))"
PHASE_REPLACE = '''    summary.update(_expire_stale_owner_messages(conn, _db_lock, db_url))
    summary.update(_expire_stale_agent_questions(conn, _db_lock, db_url))'''

EDITS = [
    (BLOCK_ANCHOR, BLOCK + BLOCK_ANCHOR, "lifecycle_sweep: question shelf life"),
    (SUMMARY_ANCHOR, SUMMARY_REPLACE, "lifecycle_sweep: summary key"),
    (PHASE_ANCHOR, PHASE_REPLACE, "lifecycle_sweep: register the phase"),
]


def main() -> int:
    text = SWEEP.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if new in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)  # accumulate on a running copy
        print(f"planned  {label}")
    SWEEP.write_text(text, encoding="utf-8")
    print(f"WROTE {SWEEP}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
