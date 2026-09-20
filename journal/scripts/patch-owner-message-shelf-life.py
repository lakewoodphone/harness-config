"""Give owner_message_queue a shelf life, and stop a send failure refreshing it.

Measured 2026-09-15 on the authority: owner_message_queue held 163 undelivered
rows -- 95 ask_owner ("CEO needs your input") from 58-109 days ago, 44 daily
briefings from 2026-08-06 onward, 10 urgent emails, 6 comms_freshness, 6
sync_breaker. Nothing in the codebase ever aged this table: the `expired` and
`superseded` rows that existed came from one-off scripts. So the kernel's
attention_debt check read "7 critical, 35 urgent held" -- CRITICAL -- for five
weeks, and 40 of those 42 were briefings whose whole value had expired within a
day. An alarm that can never go green is an alarm that gets ignored.

This patch adds the missing policy as a lifecycle-sweep phase (the sweep already
runs every 120 s) so the queue cannot rot again, and fixes the one thing that
would have defeated it: record_owner_message_send_failure stamped last_seen_at,
which is the "when was this condition last observed" clock the policy ages on.
A send attempt is not a re-observation.

Reversible by construction: status changes, bodies are never deleted.

Idempotent: refuses to apply twice, validates every anchor before writing.
"""

from __future__ import annotations

import pathlib
import sys

REPO = pathlib.Path.home() / "personal-secretary-mvp"

# ── 1. database.py: a note column, and last_seen_at stops meaning "send tried" ──
DB = REPO / "app" / "database.py"
DB_ANCHOR = '''        if "last_send_error" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN last_send_error TEXT"
            )
        conn.commit()'''
DB_REPLACE = '''        if "last_send_error" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN last_send_error TEXT"
            )
        # Why a row left the queue. Added 2026-09-15 with the shelf-life phase: until
        # then nothing aged this table at all, so a row's status was the only trace
        # that it had been dropped, and "expired" could not distinguish a five-week-old
        # briefing from a real alert.
        if "status_note" not in cols:
            conn.execute(
                "ALTER TABLE owner_message_queue ADD COLUMN status_note TEXT"
            )
        conn.commit()'''

FAIL_ANCHOR = '''    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET send_attempts = COALESCE(send_attempts, 0) + 1, "
            "last_send_error = ?, last_seen_at = ? "
            "WHERE id = ?",
            (str(reason or "")[:300], now, int(message_id)),
        )
        conn.commit()
        return cur.rowcount > 0'''
FAIL_REPLACE = '''    conn = _get_conn(db_url)
    now = _now_iso()
    with _db_lock:
        _ensure_owner_message_columns(db_url, conn)
        # last_seen_at is deliberately NOT touched here. It means "when was this
        # condition last observed" (enqueue stamps it only on a dedup hit), and the
        # shelf-life phase ages messages on it. Writing it on a failed send made a
        # five-week-old briefing look freshly seen -- which would have defeated the
        # ageing policy the same day it was added.
        cur = conn.execute(
            "UPDATE owner_message_queue "
            "SET send_attempts = COALESCE(send_attempts, 0) + 1, "
            "last_send_error = ? "
            "WHERE id = ?",
            (str(reason or "")[:300], int(message_id)),
        )
        conn.commit()
        return cur.rowcount > 0'''

# ── 2. lifecycle_sweep.py: the policy, registered as a phase ──
SWEEP = REPO / "app" / "services" / "lifecycle_sweep.py"
SWEEP_ANCHOR = "def _close_expired_drafts(conn, lock) -> int:"
SWEEP_BLOCK = '''# ── Owner message shelf life ─────────────────────────────────────────
# A queue that never forgets is not a queue, it is a landfill -- and every
# reader of it goes blind. Measured 2026-09-15: owner_message_queue held 163
# undelivered rows, 42 of them urgent/critical, and 40 of those 42 were daily
# briefings from 2026-08-06 onward whose value had expired within a day. With
# nothing ageing the table, the kernel's attention_debt check read "7 critical,
# 35 urgent held" -- CRITICAL -- for five weeks (L5: an alarm that can never go
# green is an alarm that gets ignored).
#
# The clock is COALESCE(last_seen_at, created_at). last_seen_at is stamped only
# when the identical (reason, body) is enqueued again, so it answers "when was
# this condition last observed" -- the question that decides whether an alert is
# still live. A send attempt is not re-observation, which is why
# record_owner_message_send_failure no longer writes it.
OWNER_MESSAGE_MAX_AGE_HOURS = {
    # A briefing is superseded by tomorrow's briefing; 36 h is already generous.
    "owner_briefing_morning": 36.0,
    "owner_briefing_evening": 36.0,
    # A channel-freshness signal that stopped recurring is either fixed or the
    # machinery emitting it is dead. Either way a day-old copy is not news.
    "comms_freshness": 24.0,
    # "CEO needs your input" rows: 95 of them had sat 58-109 days unanswered.
    # A week is longer than any question stays answerable and short enough that
    # the queue still means something.
    "ask_owner": 168.0,
    # Money, payroll and payment-failure mail. Long on purpose: these describe a
    # standing condition until someone fixes it, and hiding one to make a count
    # look better is worse than carrying it.
    "urgent_email": 336.0,
}
OWNER_MESSAGE_MAX_AGE_HOURS_PREFIX = (
    ("sync_breaker", 24.0),
    ("sync_needs_login", 168.0),
)
OWNER_MESSAGE_DEFAULT_MAX_AGE_HOURS = 168.0
# Reasons whose whole value is being the newest of their kind.
OWNER_MESSAGE_SUPERSEDING_REASONS = (
    "owner_briefing_morning",
    "owner_briefing_evening",
)


def _owner_message_horizon_hours(reason: str) -> float:
    """How long a held owner message stays live, by what kind of message it is."""
    raw = str(reason or "").strip()
    if raw in OWNER_MESSAGE_MAX_AGE_HOURS:
        return OWNER_MESSAGE_MAX_AGE_HOURS[raw]
    for prefix, hours in OWNER_MESSAGE_MAX_AGE_HOURS_PREFIX:
        if raw.startswith(prefix):
            return hours
    return OWNER_MESSAGE_DEFAULT_MAX_AGE_HOURS


def _expire_stale_owner_messages(conn, lock, db_url) -> dict[str, int]:
    """Age out undelivered owner messages whose moment has passed.

    Two rules, applied only to `held`/`queued` rows, both reversible (status is
    changed and `status_note` records why; bodies are never deleted):

      1. past its reason's horizon -> `expired`
      2. an older briefing sitting beside a newer one of the same kind -> `superseded`
    """
    counts = {"owner_messages_expired": 0, "owner_messages_superseded": 0}
    try:
        from app.database import _ensure_owner_message_columns

        _ensure_owner_message_columns(db_url, conn)
        rows = conn.execute(
            "SELECT DISTINCT reason FROM owner_message_queue "
            "WHERE status IN ('held', 'queued')"
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - a missing table is not this phase's problem
        log.warning("lifecycle sweep: owner message ageing skipped: %s", exc)
        return counts

    now = datetime.now(timezone.utc)
    try:
        with lock:
            for row in rows:
                reason = str(row[0] or "")
                hours = _owner_message_horizon_hours(reason)
                cutoff = (now - timedelta(hours=hours)).isoformat()
                cur = conn.execute(
                    "UPDATE owner_message_queue SET status = 'expired', status_note = ? "
                    "WHERE status IN ('held', 'queued') AND reason = ? "
                    "AND datetime(COALESCE(last_seen_at, created_at)) < datetime(?)",
                    (f"expired: held longer than {hours:g}h", reason, cutoff),
                )
                counts["owner_messages_expired"] += int(cur.rowcount or 0)
            for reason in OWNER_MESSAGE_SUPERSEDING_REASONS:
                cur = conn.execute(
                    "UPDATE owner_message_queue SET status = 'superseded', "
                    "status_note = ? "
                    "WHERE status IN ('held', 'queued') AND reason = ? AND id NOT IN ("
                    "SELECT id FROM owner_message_queue WHERE reason = ? "
                    "AND status IN ('held', 'queued') "
                    "ORDER BY created_at DESC LIMIT 1)",
                    (f"superseded by a newer {reason}", reason, reason),
                )
                counts["owner_messages_superseded"] += int(cur.rowcount or 0)
            conn.commit()
    except Exception as exc:  # noqa: BLE001 - the sweep must survive a bad phase
        log.warning("lifecycle sweep: owner message ageing failed: %s", exc)
    return counts


'''
SWEEP_SUMMARY_ANCHOR = '        "drafts_expired": 0,'
SWEEP_SUMMARY_REPLACE = '''        "drafts_expired": 0,
        "owner_messages_expired": 0,
        "owner_messages_superseded": 0,'''
SWEEP_PHASE_ANCHOR = '    summary["drafts_expired"] = _close_expired_drafts(conn, _db_lock)'
SWEEP_PHASE_REPLACE = '''    summary["drafts_expired"] = _close_expired_drafts(conn, _db_lock)
    summary.update(_expire_stale_owner_messages(conn, _db_lock, db_url))'''

EDITS = [
    (DB, DB_ANCHOR, DB_REPLACE, "database.py: status_note column"),
    (DB, FAIL_ANCHOR, FAIL_REPLACE, "database.py: send failure stops stamping last_seen_at"),
    (SWEEP, SWEEP_ANCHOR, SWEEP_BLOCK + SWEEP_ANCHOR, "lifecycle_sweep.py: shelf-life policy"),
    (SWEEP, SWEEP_SUMMARY_ANCHOR, SWEEP_SUMMARY_REPLACE, "lifecycle_sweep.py: summary keys"),
    (SWEEP, SWEEP_PHASE_ANCHOR, SWEEP_PHASE_REPLACE, "lifecycle_sweep.py: register the phase"),
]


def main() -> int:
    # Validate every anchor on the current bytes before writing anything.
    plans = []
    for path, old, new, label in EDITS:
        text = path.read_text(encoding="utf-8")
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1) in {path}")
            return 2
        if new in text:
            print(f"REFUSE {label}: replacement already present (already applied?)")
            return 2
        plans.append((path, text, old, new, label))

    for path, text, old, new, label in plans:
        path.write_text(text.replace(old, new, 1), encoding="utf-8")
        print(f"ok  {label}")

    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
