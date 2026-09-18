"""attention_debt must measure live debt, not archaeology.

Two defects, both measured 2026-09-15:

1. **It counted a dead channel's backlog as live owner work.** 313 pending
   `agent_questions`, oldest 134 days, **none created in 30 days** -- the badge line
   read "oldest question 134d old" permanently. The app's shelf life now expires those
   (they are all >14 days), and this check counts only questions young enough to still
   be answerable.

2. **Severity was a bare count.** `CRITICAL if critical else HIGH` meant two *six-day-old*
   Google security alerts held the owner's whole badge red, with no way to go green
   except the rows ageing out 14 days later. An alarm that can never go green is an alarm
   that gets ignored -- which is the failure the shelf-life work already repaired one
   layer down. CRITICAL now means "a critical alert was observed within 48 hours", where
   "observed" is the same clock the shelf life uses (`COALESCE(last_seen_at, created_at)`),
   and the summary states the age so a HIGH reads as what it is.
"""

from __future__ import annotations

import pathlib
import sys

SENT = pathlib.Path("/home/zabz/ceo-kernel/ck/sentinel.py")

ANCHOR1 = '''def check_attention_debt(max_oldest_hours: float = 48.0) -> Finding:
    """Unanswered questions and undelivered messages, with their true age.

    History: 313 questions pending with none created since 19 July, and 7
    `critical` plus 46 `urgent` messages held undelivered.
    """
    pending = sources.scalar(
        "SELECT COUNT(*) FROM agent_questions WHERE status='pending'",
        name="pending_questions",
    )
    oldest = sources.scalar(
        "SELECT MIN(created_at) FROM agent_questions WHERE status='pending'",
        name="oldest_pending_question",
    )
    held = sources.rows(
        "SELECT status, urgency, COUNT(*) AS n FROM owner_message_queue "
        "WHERE status='held' GROUP BY status, urgency ORDER BY n DESC",
        name="held_messages",
    )'''

REPLACE1 = '''# A question nobody answered within two weeks is not a question any more -- the app's
# lifecycle sweep expires it. An alert last observed more than two days ago is not a
# reason to keep the owner's badge red: CRITICAL here means "live now".
QUESTION_DEBT_HOURS = 336.0
FRESH_CRITICAL_HOURS = 48.0


def check_attention_debt(max_oldest_hours: float = 48.0) -> Finding:
    """Unanswered questions and undelivered messages, with their true age.

    History: 313 questions pending with none created since 19 July (measured
    2026-09-15: oldest 134 days, nothing new in 30), and 7 `critical` plus 46 `urgent`
    messages held undelivered. Both numbers were counted as live owner debt, which kept
    this check CRITICAL for five weeks.
    """
    question_window = "-%d hours" % int(QUESTION_DEBT_HOURS)
    pending = sources.scalar(
        "SELECT COUNT(*) FROM agent_questions WHERE status='pending' "
        "AND datetime(created_at) >= datetime('now', ?)",
        (question_window,),
        name="recent_pending_questions",
    )
    stale_pending = sources.scalar(
        "SELECT COUNT(*) FROM agent_questions WHERE status='pending' "
        "AND datetime(created_at) < datetime('now', ?)",
        (question_window,),
        name="stale_pending_questions",
    )
    oldest = sources.scalar(
        "SELECT MIN(created_at) FROM agent_questions WHERE status='pending' "
        "AND datetime(created_at) >= datetime('now', ?)",
        (question_window,),
        name="oldest_recent_question",
    )
    held = sources.rows(
        "SELECT status, urgency, COUNT(*) AS n FROM owner_message_queue "
        "WHERE status='held' GROUP BY status, urgency ORDER BY n DESC",
        name="held_messages",
    )
    # Severity follows how recently a held alert was *observed*, from the same clock the
    # shelf life ages on -- so a stale critical cannot hold the badge red for ever.
    held_ages = sources.rows(
        "SELECT urgency, COALESCE(last_seen_at, created_at) AS seen_at "
        "FROM owner_message_queue WHERE status='held'",
        name="held_ages",
    )'''

ANCHOR2 = '''    refusals = [r for p in (pending, oldest, held, held_samples) for r in p.refusals]
    prov = [_pkt_note(p) for p in (pending, oldest, held, held_samples)]

    if not pending.usable or not held.usable:'''

REPLACE2 = '''    packets = (pending, stale_pending, oldest, held, held_ages, held_samples)
    refusals = [r for p in packets for r in p.refusals]
    prov = [_pkt_note(p) for p in packets]

    if not pending.usable or not held.usable or not held_ages.usable:'''

ANCHOR3 = '''    metrics = {
        "pending_questions": int(pending.value or 0),
        "held_headlines": held_headlines,
        "oldest_pending_hours": round(oldest_hours, 1) if oldest_hours else None,
        "held_total": held_total,
        "held_critical": critical,
        "held_urgent": urgent,
        "held_breakdown": held_rows,
    }

    problems: list[str] = []
    if critical:
        problems.append(f"{critical} critical message(s) held")
    if urgent:
        problems.append(f"{urgent} urgent message(s) held")
    if held_headlines:
        # The one line the badge shows now says what is waiting.
        problems.append("waiting: " + " | ".join(held_headlines))
    if oldest_hours and oldest_hours > max_oldest_hours:
        problems.append(f"oldest question {oldest_hours/24:.0f}d old")

    if problems:
        sev = CRITICAL if critical else HIGH'''

REPLACE3 = '''    now = pv.now()
    fresh_critical = 0
    fresh_urgent = 0
    newest_age_h: float | None = None
    for row in (dict(r) for r in (held_ages.value or [])):
        seen = pv.parse_stamp(row.get("seen_at")) if row.get("seen_at") else None
        if seen is None:
            continue
        age_h = (now - seen).total_seconds() / 3600
        newest_age_h = age_h if newest_age_h is None else min(newest_age_h, age_h)
        if age_h <= FRESH_CRITICAL_HOURS:
            if str(row.get("urgency")) == "critical":
                fresh_critical += 1
            elif str(row.get("urgency")) == "urgent":
                fresh_urgent += 1

    metrics = {
        "pending_questions": int(pending.value or 0),
        "stale_pending_questions": int(stale_pending.value or 0),
        "question_debt_window_hours": QUESTION_DEBT_HOURS,
        "held_headlines": held_headlines,
        "oldest_pending_hours": round(oldest_hours, 1) if oldest_hours else None,
        "held_total": held_total,
        "held_critical": critical,
        "held_urgent": urgent,
        "held_critical_fresh": fresh_critical,
        "held_urgent_fresh": fresh_urgent,
        "newest_held_age_hours": (
            round(newest_age_h, 1) if newest_age_h is not None else None
        ),
        "fresh_within_hours": FRESH_CRITICAL_HOURS,
        "held_breakdown": held_rows,
    }

    problems: list[str] = []
    if critical:
        age_note = (
            f", newest {newest_age_h/24:.1f}d old" if newest_age_h is not None else ""
        )
        problems.append(f"{critical} critical message(s) held{age_note}")
    if urgent:
        problems.append(f"{urgent} urgent message(s) held")
    if held_headlines:
        # The one line the badge shows now says what is waiting.
        problems.append("waiting: " + " | ".join(held_headlines))
    if oldest_hours and oldest_hours > max_oldest_hours:
        problems.append(f"oldest question {oldest_hours/24:.0f}d old")
    if int(stale_pending.value or 0):
        # Not debt: the channel is dormant and the shelf life is expiring these. Stated
        # so a reader does not have to wonder where 313 questions went.
        metrics["stale_questions_note"] = (
            "%d pending question(s) older than %d days are not counted as live debt"
            % (int(stale_pending.value or 0), int(QUESTION_DEBT_HOURS / 24))
        )

    if problems:
        # CRITICAL only for something critical observed inside the freshness window; a
        # stale critical is HIGH and says its age. This is what lets the badge go green.
        sev = CRITICAL if fresh_critical else HIGH'''

ANCHOR4 = '''        summary=f"attention debt within bounds "
                f"({int(pending.value or 0)} pending, {held_total} held)",'''

REPLACE4 = '''        summary=f"attention debt within bounds "
                f"({int(pending.value or 0)} recent question(s), {held_total} held, "
                f"none fresh)",'''

EDITS = [
    (ANCHOR1, REPLACE1, "attention_debt: recent questions + observation ages"),
    (ANCHOR2, REPLACE2, "attention_debt: provenance covers the new packets"),
    (ANCHOR3, REPLACE3, "attention_debt: freshness decides severity"),
    (ANCHOR4, REPLACE4, "attention_debt: the green line says what it means"),
]


def main() -> int:
    text = SENT.read_text(encoding="utf-8")
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
    SENT.write_text(text, encoding="utf-8")
    print(f"WROTE {SENT}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
