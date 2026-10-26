"""Goal Lifecycle Sweep — Periodic goal health management.

Directive 013: Goal Lifecycle Management & Agent Output Verification.

Runs on a configurable interval (default 120 s) inside the autopilot loop.
Each sweep performs five phases:

1. Release stale claims — running steps with no heartbeat > 10 min
2. Retry failed steps — exponential backoff with jitter
3. Reopen stale blocked steps — blocked in active goals, cooldown elapsed
4. Goal state rollup — all steps done → complete the goal
5. Stuck detection — active goal with no progress > 2 h → escalate
6. Superseded cleanup — mark old goals replaced by newer ones
"""

from __future__ import annotations

import json
import logging
import random
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# ── Constants ────────────────────────────────────────────────────────

STALE_HEARTBEAT_MINUTES = 10
STUCK_GOAL_HOURS = 12
# Blocked steps in ACTIVE goals are reopened after this many hours so a
# now-resolved root cause (e.g. the 2026-08-30 empty-tool-name bug that
# blocked 7+ steps with "meta-only" errors) does not permanently starve
# a goal. Reopen resets attempts/error so the pre-flight skip checks no
# longer fire and the step gets a real LLM call.
BLOCKED_REOPEN_HOURS = 6
# Maximum times a single blocked step is auto-reopened before it stays
# blocked permanently (genuinely unworkable steps must not churn budget
# forever — they should get human/CEO review instead).
BLOCKED_REOPEN_MAX = 2
# CRITICAL FIX (2026-08-09): goals that stay stuck after this many
# escalations are auto-cancelled instead of re-escalating forever.
# Combined with the 24h P2 cooldown (escalation_router.py), a stuck goal
# can fire at most 2 escalations over ~48h before it is retired.
ESCALATION_DIE_THRESHOLD = 2
BACKOFF_BASE_SEC = 30
BACKOFF_MULTIPLIER = 2
BACKOFF_CAP_SEC = 1800

# Standing work orders that are marked 'running' but have not finished
# within this window are presumed crashed. Sweep marks them 'failed'
# and bumps next_run_after so they re-fire on the next tick.
STUCK_WORK_ORDER_MINUTES = 30
# FIX (2026-08-31): agent turn cadence is 20-71 min per agent (company
# tick rounds-robin all agents), so a multi-step WO goal routinely waits
# longer than STUCK_WORK_ORDER_MINUTES between claims even while making
# steady progress. A goal whose LAST step completion is inside this wider
# window is still alive and must NOT be released as stale. The window is
# bounded so old completions never protect forever (avoids the 2026-08-30
# deadlock where any completed step protected a goal up to 12h).
STUCK_WORK_ORDER_PROGRESS_WINDOW_MINUTES = 90

# ── The windows must not be shorter than the fleet's own turn cadence ──────
#
# Measured 2026-10-02 on the authority, from `tick_telemetry`, for the six
# standing work orders that quarantined with "stuck execution" on 2026-09-30/
# 10-01: department agents claim at most ONE step per tick, and their turn
# cadence is far slower than the fixed windows above:
#   * dept_engineering: ticks at 17:27:45 and 18:54:xx on 2026-09-30 -- 87 min
#     apart; 36 ticks over the 47 h from 2026-09-30T00:00 to 2026-10-01T23:15
#     -> ~78 min per tick.
#   * `swo_seed_eng_health_22e90471` was created at 17:27:45 and its step was
#     still unclaimed when the sweep released the execution at 17:58:11 --
#     30.4 min, i.e. the goal died inside the FIRST window (30 min) because the
#     agent's next turn simply had not arrived yet.
#   * `swo_seed_eng_filter_ai_daily_push_3e214301`: step 1 completed 06:50:26,
#     step 2 completed 07:50:32 (60 min apart), step 3 was next in the queue and
#     the execution was released at 09:20:43, 90 min after step 2.
#   * `swo_seed_lpt_pricing_reconcile_f84aafdc`: step 2 completed 13:05:50 and
#     the execution was released at 14:36:18, 90 min later, with step 3 pending.
# A fixed window cannot express this: it was written for a 10-15 min tick world
# and the fleet now turns over once an hour. So the window is DERIVED from the
# goal's own department cadence (median gap between that agent's recent ticks),
# with the values above as the floor, and capped so a stalled agent cannot
# protect a goal forever.
STUCK_WORK_ORDER_MAX_MINUTES = 360
STUCK_WORK_ORDER_CADENCE_MULTIPLIER = 3.0
STUCK_PROGRESS_WINDOW_MAX_MINUTES = 480
STUCK_PROGRESS_WINDOW_CADENCE_MULTIPLIER = 2.0
DEPARTMENT_CADENCE_SAMPLE = 20
DEPARTMENT_CADENCE_MIN_SAMPLES = 4


# VP/CoS Round 2 follow-up: stale in_progress tasks block the active task
# ceiling and jam the entire system. Auto-close after this many days of
# no updates. Tasks closed this way get a clear note so the CoS knows.
STALE_TASK_DAYS = 7
BACKOFF_JITTER = 0.25
MAX_RETRIES = 5
STALE_APPROVAL_HOURS = 2
# How long an owner-facing approval TASK stays open before the sweep closes it
# unanswered (it grants nothing when it does). Long enough to be seen in a working
# day, short enough that the queue cannot become a dumping ground: measured
# 2026-10-26, 108 open approval tasks were holding a 300-task ceiling shut.
STALE_APPROVAL_TASK_HOURS = 48
TASK_GOAL_COVERAGE_LIMIT = 10
TASK_GOAL_COVERAGE_QUERY_MULTIPLIER = 8
TASK_GOAL_COVERAGE_AGENT_ACTIVE_LIMIT = 3
TASK_GOAL_COVERAGE_PRIORITIES = {
    "critical": 95,
    "urgent": 90,
    "high": 80,
    "medium": 60,
}


def _backoff_delay(attempts: int) -> float:
    """Exponential backoff with jitter.

    delay = min(base × mult^attempts, cap) × (1 ± jitter)
    """
    delay = min(
        BACKOFF_BASE_SEC * (BACKOFF_MULTIPLIER**attempts),
        BACKOFF_CAP_SEC,
    )
    jitter = delay * BACKOFF_JITTER * (2 * random.random() - 1)
    return max(0, delay + jitter)


# ── Owner message shelf life ─────────────────────────────────────────
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
    # A reminder is time-bound by nature: one the owner has not acted on in a day is a
    # stale nag, and the item itself is still open in `reminders` either way.
    ("reminder", 24.0),
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


def _file_owner_questions(conn, lock, db_url) -> int:
    """File held owner questions onto the decision queue before they can expire.

    Runs ahead of `_expire_stale_owner_messages` on purpose: the horizon for
    `ask_owner` is 168 h, and until 2026-09-23 the only thing that happened at the
    end of it was `expired` -- the question vanished from every surface. It could
    never be sent either, because the ask path files at urgency `normal` and the
    send gate requires `urgent` (his 2026-09-22 instruction). Measured that day:
    10 questions held, none of them on the queue, the newest question ever
    delivered 2026-04-16T12:00Z.

    The routing itself lives in `app/services/owner_question_queue.py`, which is
    idempotent and additive. This wrapper only supplies the sweep's lock and keeps
    a broken phase from taking the sweep down.
    """
    try:
        from app.services.owner_question_queue import file_owner_questions

        with lock:
            result = file_owner_questions(conn)
        filed = int(result.get("filed") or 0)
        if filed:
            log.info(
                "lifecycle sweep: filed %d owner question(s) on the decision queue: %s",
                filed,
                result.get("ids"),
            )
        return filed
    except Exception as exc:  # noqa: BLE001 - the sweep must survive a bad phase
        log.warning("lifecycle sweep: owner question routing failed: %s", exc)
        return 0


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


# ── Agent question shelf life ────────────────────────────────────────
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


def _close_expired_drafts(conn, lock) -> int:
    """Close email drafts whose own expires_at has passed.

    email_drafts has carried expires_at since it was created and nothing ever
    read it, so drafts from 2026-06 were still pending_review on 2026-09-14,
    waiting for a review that was never offered. A draft too old to send is not
    a pending decision; it is clutter in the only queue the owner reads.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    try:
        with lock:
            cur = conn.execute(
                "UPDATE email_drafts SET status = 'expired', "
                "rejection_reason = coalesce(rejection_reason, 'expired before review') "
                "WHERE status = 'pending_review' "
                "AND expires_at IS NOT NULL AND expires_at < ?",
                (now,),
            )
            conn.commit()
            return int(cur.rowcount or 0)
    except Exception as exc:
        log.warning("lifecycle sweep: draft expiry failed: %s", exc)
        return 0


def run_lifecycle_sweep(db_url: str) -> dict:
    """Execute all lifecycle sweep phases.

    Returns a summary dict with counts for each phase.
    """
    from app.database import _db_lock, _get_conn, ensure_task_lifecycle_metadata

    conn = _get_conn(db_url)
    summary: dict[str, int] = {
        "stale_released": 0,
        "retries_scheduled": 0,
        "blocked_reopened": 0,
        "goals_completed": 0,
        "stuck_escalated": 0,
        "superseded_cleaned": 0,
        "work_orders_unstuck": 0,
        "task_lifecycle_updated": 0,
        "completed_progress_tasks_closed": 0,
        "active_task_progress_synced": 0,
        "priority_task_goals_created": 0,
        "terminal_waiting_steps_cleaned": 0,
        "drafts_expired": 0,
        "owner_messages_expired": 0,
        "owner_questions_filed": 0,
        "agent_questions_expired": 0,
        "owner_messages_superseded": 0,
        "customer_stalls_open": 0,
        "customer_stall_detected": 0,
        "customer_stalls_realerted": 0,
    }

    lifecycle_summary = ensure_task_lifecycle_metadata(db_url)
    summary["task_lifecycle_updated"] = int(lifecycle_summary.get("updated", 0))
    summary["completed_progress_tasks_closed"] = _close_completed_progress_tasks(
        conn,
        _db_lock,
        db_url,
    )
    summary["active_task_progress_synced"] = _sync_active_task_progress_from_goals(
        conn,
        _db_lock,
        db_url,
    )
    summary["priority_task_goals_created"] = _ensure_priority_task_goal_coverage(
        conn,
        _db_lock,
        db_url,
    )
    summary["drafts_expired"] = _close_expired_drafts(conn, _db_lock)
    summary["owner_questions_filed"] = _file_owner_questions(conn, _db_lock, db_url)
    summary.update(_expire_stale_owner_messages(conn, _db_lock, db_url))
    summary.update(_expire_stale_agent_questions(conn, _db_lock, db_url))
    summary["stale_released"] = _release_stale_claims(conn, _db_lock)
    summary["retries_scheduled"] = _retry_failed_steps(conn, _db_lock)
    summary["blocked_reopened"] = _reopen_stale_blocked_steps(conn, _db_lock)
    summary["goals_completed"] = _rollup_completed_goals(
        conn,
        _db_lock,
        db_url,
    )
    summary["stuck_escalated"] = _detect_stuck_goals(conn, _db_lock, db_url)
    summary["superseded_cleaned"] = _cleanup_superseded(conn, _db_lock)
    summary["approvals_expired"] = _expire_stale_approvals(
        conn,
        _db_lock,
    )
    summary["terminal_waiting_steps_cleaned"] = _cleanup_terminal_waiting_steps(
        conn,
        _db_lock,
    )
    # Runs BEFORE _close_stale_tasks: the stall watch has to see a stalled
    # customer job in the same pass that might otherwise auto-close it.
    # _close_stale_tasks also now refuses recognisable customer work outright.
    summary.update(_watch_customer_stalls(db_url))
    summary["stale_tasks_closed"] = _close_stale_tasks(conn, _db_lock, db_url)
    summary["work_orders_unstuck"] = _release_stuck_work_orders(
        conn,
        _db_lock,
    )

    log.info("Lifecycle sweep complete: %s", summary)
    return summary


def _watch_customer_stalls(db_url: str) -> dict[str, int]:
    """Customer stall watch phase (flagged, never sent).

    Customer repairs have historically been the one class of task that no phase
    here could see: `_close_stale_tasks` filters on `status IN ('in_progress',
    'open')`, and the three live forgotten repairs (#3132, #4467, #4485) are the
    only rows in the whole table spelled `'in-progress'`, so the reaper could not
    see them. This phase does, and it reports them on the same summary dict the
    autopilot already logs.

    Never raises: a bad phase must not disable every other lifecycle phase.
    """
    out = {
        "customer_stalls_open": 0,
        "customer_stall_detected": 0,
        "customer_stalls_realerted": 0,
    }
    try:
        from app.services.customer_stall_watch import run_customer_stall_watch

        watch = run_customer_stall_watch(db_url)
        out["customer_stalls_open"] = int(watch.get("stalls_open", 0) or 0)
        out["customer_stall_detected"] = int(watch.get("stalls_detected", 0) or 0)
        out["customer_stalls_realerted"] = int(watch.get("stalls_realerted", 0) or 0)
    except Exception as exc:  # noqa: BLE001 - the sweep must survive a bad phase
        log.warning("lifecycle sweep: customer stall watch failed: %s", exc)
    return out


def _task_goal_priority(priority: str | None) -> int:
    return TASK_GOAL_COVERAGE_PRIORITIES.get(str(priority or "").strip().lower(), 50)


def _load_active_goal_agent_ids() -> set[str]:
    """Return active worker IDs that can actually claim goal steps."""
    try:
        from app.config import settings

        store_path = Path(settings.identity_store_path)
        if not store_path.exists():
            return set()
        data = json.loads(store_path.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        log.debug("Unable to load active goal agent IDs: %s", exc)
        return set()

    agents = data.get("agents") if isinstance(data, dict) else None
    if not isinstance(agents, dict):
        return set()

    active: set[str] = set()
    for agent_id, agent in agents.items():
        if not isinstance(agent, dict):
            continue
        top_status = str(agent.get("status") or "active").lower()
        dept = agent.get("department") if isinstance(agent.get("department"), dict) else {}
        dept_status = str(dept.get("status") or "active").lower()
        if top_status in {"deactivated", "retired", "fired"}:
            continue
        if dept_status not in {"", "active"}:
            continue
        active.add(str(agent_id))
    return active


def _board_seat_execution_refusal(agent_id: str | None, task: Any) -> dict[str, Any] | None:
    """The governance-seat guard, borrowed from `workforce.delegate_task`.

    A board seat reviews, approves or refuses a proposal -- it does not execute.
    That rule already lives in `app.workforce._board_seat_execution_refusal` and is
    enforced at the delegation writer. This module is the OTHER writer of the same
    mistake, so it asks the same function rather than keeping a second copy of the
    rule that can drift from it.

    Imported lazily: `app.workforce` is a large module and this sweep has no other
    reason to depend on it. An import failure propagates into the per-row handler in
    `_ensure_priority_task_goal_coverage`, which skips the row -- the safe direction,
    because the alternative is rebuilding exactly the doomed goal this refuses.
    """
    from app.workforce import _board_seat_execution_refusal as _guard

    return _guard(agent_id, _goal_coverage_task(task))


def _goal_coverage_task(row: Any) -> dict[str, Any]:
    """The row the guard needs, as a plain dict.

    `_board_seat_execution_refusal` reads `task["id"]`, `task["title"]` and
    `task["tags_json"]`, and a `sqlite3.Row` supports none of the `.get()` calls it
    makes -- passing the row straight through raised, and the per-row handler turned
    that into a silent skip of EVERY board-seat row, including the governance reviews
    the seat is supposed to take. `tags_json` is in the coverage query for exactly
    this reason: without it a tagged board packet looks like execution work.
    """
    if isinstance(row, dict):
        return row
    keys = row.keys() if hasattr(row, "keys") else ()

    def _val(name: str, default: Any = "") -> Any:
        return row[name] if name in keys else default

    return {
        "id": _val("id"),
        "title": _val("title"),
        "description": _val("description"),
        "tags_json": _val("tags_json", "[]"),
    }


def _ensure_priority_task_goal_coverage(
    conn,
    lock,
    db_url: str,
    *,
    limit: int = TASK_GOAL_COVERAGE_LIMIT,
) -> int:
    """Create goal coverage for assigned active tasks with no active goal.

    Some tasks are created or updated with ``assigned_to`` already populated,
    bypassing ``workforce.delegate_task()`` and therefore never entering the
    goal/step lane consumed by department workers. This conservative backfill
    covers normal department-priority work, leaves assignment unchanged, caps
    active goals per agent, and dedupes against active/pending goal plans.
    """
    created_limit = max(1, int(limit))
    query_limit = max(
        created_limit,
        created_limit * TASK_GOAL_COVERAGE_QUERY_MULTIPLIER,
    )
    # CRITICAL FIX (2026-08-08): A task whose goal recently completed or
    # failed would reappear as "no active goal" on the very next sweep,
    # and we created a brand-new goal for it — 1,054 goal re-creations
    # in 2 days, each feeding the LLM work loop. Skip any task that had
    # ANY goal_plan (any status) in the last 24h, not just active ones.
    recent_goal_cutoff = (
        datetime.now(timezone.utc) - timedelta(hours=24)
    ).isoformat()
    # The recency filter references goal_plans.created_at; minimal test
    # fixtures may lack that column, in which case fall back to the
    # historical active-only dedup (production always has created_at).
    goal_plans_columns = {
        str(row["name"])
        for row in conn.execute("PRAGMA table_info(goal_plans)").fetchall()
    }
    task_columns = {
        str(row["name"]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }
    # The guard needs the task's tags to tell governance work from execution work,
    # but a minimal `tasks` fixture (and any older schema) may not carry the column.
    # Absent, the guard sees no tags and falls back to the title, which is the same
    # one-sided default `workforce._board_seat_execution_refusal` already documents:
    # refusing a real review costs a retry, accepting an execution task costs a tick
    # every time it is attempted.
    task_tags_expr = "t.tags_json" if "tags_json" in task_columns else "'[]' AS tags_json"

    recent_goal_clause = ""
    recent_goal_params: tuple[Any, ...] = ()
    if "created_at" in goal_plans_columns:
        recent_goal_clause = (
            "               AND NOT EXISTS (\n"
            "                     SELECT 1\n"
            "                       FROM goal_plans gp_recent\n"
            "                      WHERE gp_recent.parent_task_id = t.id\n"
            "                        AND gp_recent.created_at >= ?\n"
            "               )\n"
        )
        recent_goal_params = (recent_goal_cutoff,)
    try:
        rows = conn.execute(
            """
            SELECT t.id, t.title, t.description, t.priority,
                   t.assigned_to, t.agent_id, """ + task_tags_expr + """,
                   COALESCE((
                       SELECT COUNT(*)
                         FROM goal_plans gp2
                        WHERE gp2.assigned_agent = COALESCE(t.assigned_to, t.agent_id)
                          AND gp2.status IN ('active', 'pending')
                   ), 0) AS active_goal_count
              FROM tasks t
              LEFT JOIN goal_plans gp
                ON gp.parent_task_id = t.id
               AND gp.status IN ('active', 'pending')
             WHERE t.status IN ('open', 'in_progress', 'pending')
               AND lower(t.priority) IN ('critical', 'urgent', 'high', 'medium')
               AND COALESCE(t.assigned_to, t.agent_id, '') != ''
               AND gp.id IS NULL
""" + recent_goal_clause + """             ORDER BY active_goal_count ASC,
                      CASE lower(t.priority)
                        WHEN 'critical' THEN 3
                        WHEN 'urgent' THEN 2
                        WHEN 'high' THEN 1
                        WHEN 'medium' THEN 0
                        ELSE 0
                      END DESC,
                      t.updated_at ASC
             LIMIT ?
            """,
            (*recent_goal_params, query_limit),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.debug("Task goal coverage query failed: %s", exc)
        return 0

    if not rows:
        return 0

    try:
        from app.database import canonicalize_assignment_agent, log_activity
        from app.services.workflow_engine import WorkflowEngine
    except Exception as exc:  # noqa: BLE001
        log.debug("Priority task goal coverage imports failed: %s", exc)
        return 0

    created = 0
    active_goal_count_by_agent: dict[str, int] = {}
    active_goal_agent_ids = _load_active_goal_agent_ids()
    engine = WorkflowEngine(db_url)
    for row in rows:
        try:
            target_agent = canonicalize_assignment_agent(
                row["assigned_to"] or row["agent_id"]
            )
            if not target_agent or target_agent == "orchestrator":
                continue

            # ── A board seat reviews; it does not execute (measured 2026-10-12) ──
            # This sweep is the SECOND ingress for that mistake, and the reason the
            # first fix did not end it. `workforce.delegate_task` refuses execution
            # work aimed at a governance seat (2026-10-02), but this backfill exists
            # precisely to cover tasks whose `assigned_to` was set WITHOUT going
            # through `delegate_task` -- and it carried no such guard, so it rebuilt
            # the goal every day.
            #
            # MEASURED, and this is what the kernel reported as `agent_dead_weight`
            # ("frontier_risk_board with 30 ticks and 0 completions"): task #27207
            # ("Pay Yisroel Weinberg the 597.29 net cash settlement", tags [],
            # assigned_to=frontier_risk_board) was re-planned into a goal for the
            # risk seat on 2026-10-07 and again on 2026-10-08. Every one of those
            # ticks could only end in the seat's own refusal -- all 29 of its steps in
            # the window came back `skipped` with the same "Cannot execute payment
            # step. This is an owner-act..." text, against 572 skipped / 75 completed
            # all-time. The seat was behaving correctly; the planner was wrong.
            #
            # Refuse, never substitute: a silent reroute would hide the misassignment
            # that produced the choice, which is the same reason `delegate_task`
            # refuses instead of re-routing. Assignment is left unchanged, exactly as
            # this sweep already promises.
            board_refusal = _board_seat_execution_refusal(target_agent, row)
            if board_refusal is not None:
                log.warning(
                    "task goal coverage refused for task %s -> %s: %s",
                    row["id"],
                    target_agent,
                    board_refusal["error"],
                )
                try:
                    log_activity(
                        db_url,
                        action="task_goal_coverage_refused",
                        detail=(
                            f"Refused goal coverage for task #{row['id']} -> "
                            f"{target_agent}: {board_refusal['reason']}"
                        ),
                        agent_id="lifecycle_sweep",
                        details={
                            "task_id": int(row["id"]),
                            "requested_agent_id": target_agent,
                            "reason": board_refusal["reason"],
                        },
                    )
                except Exception:
                    pass
                continue

            if active_goal_agent_ids and target_agent not in active_goal_agent_ids:
                log.debug(
                    "Skipping task goal coverage for task %s: target agent %s is not active",
                    row["id"],
                    target_agent,
                )
                continue

            if target_agent not in active_goal_count_by_agent:
                active_goal_count_by_agent[target_agent] = int(
                    conn.execute(
                        """SELECT COUNT(*) AS c
                           FROM goal_plans
                          WHERE assigned_agent = ?
                            AND status IN ('active', 'pending')""",
                        (target_agent,),
                    ).fetchone()["c"]
                )
            if (
                active_goal_count_by_agent[target_agent]
                >= TASK_GOAL_COVERAGE_AGENT_ACTIVE_LIMIT
            ):
                continue

            task_id = int(row["id"])
            title = str(row["title"] or f"Task #{task_id}").strip()
            description = str(row["description"] or "").strip()
            priority = _task_goal_priority(row["priority"])
            step_description = description or f"Execute priority task: {title}"
            step_description += (
                "\n\nRespect communications and approval boundaries: do not send "
                "LPT customer-facing SMS, email, or calls from this goal without "
                "explicit current owner approval; route irreversible spend, login, "
                "or sensitive commitments for owner decision."
            )

            engine.create_goal(
                title=title,
                objective=description or title,
                steps=[
                    {
                        "title": title,
                        "description": step_description,
                        "agent": target_agent,
                    }
                ],
                priority=priority,
                source="delegation",
                source_ref=str(task_id),
                assigned_agent=target_agent,
                parent_task_id=task_id,
                context={"created_by": "lifecycle_priority_task_goal_coverage"},
            )
            created += 1
            active_goal_count_by_agent[target_agent] += 1
            try:
                log_activity(
                    db_url,
                    action="task_goal_coverage_created",
                    detail=f"Created goal coverage for task #{task_id}: {title[:120]}",
                    agent_id="lifecycle_sweep",
                    details={
                        "task_id": task_id,
                        "assigned_to": target_agent,
                        "priority": row["priority"],
                    },
                )
            except Exception:
                pass
            if created >= created_limit:
                break
        except Exception as exc:  # noqa: BLE001
            log.debug("Failed to create task goal coverage for task %s: %s", row["id"], exc)
            continue

    if created:
        log.info("Created goal coverage for %d assigned task(s)", created)
    return created


def _parse_iso_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _active_work_order_goal_is_recent(conn, goal_plan_id: str | None) -> bool:
    if not goal_plan_id:
        return False
    row = conn.execute(
        "SELECT status, updated_at FROM goal_plans WHERE id = ?",
        (goal_plan_id,),
    ).fetchone()
    if not row or row["status"] != "active":
        return False

    updated_at = _parse_iso_datetime(row["updated_at"])
    if updated_at is None:
        return True
    cutoff = datetime.now(timezone.utc) - timedelta(hours=STUCK_GOAL_HOURS)
    return updated_at >= cutoff


def _cleanup_terminal_waiting_steps(conn, lock) -> int:
    """Clear actionable-looking steps whose parent goal is already terminal."""
    with lock:
        rows = conn.execute(
            """SELECT gs.id
               FROM goal_steps gs
               JOIN goal_plans gp ON gp.id = gs.goal_id
               WHERE gs.status IN ('pending', 'blocked', 'running', 'waiting_approval')
                 AND gp.status IN ('completed', 'cancelled', 'failed')""",
        ).fetchall()
        if not rows:
            return 0

        step_ids = [row["id"] for row in rows]
        placeholders = ",".join("?" for _ in step_ids)
        conn.execute(
            f"""UPDATE goal_steps
                SET status = 'skipped',
                    completed_at = COALESCE(completed_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
                    result_summary = COALESCE(
                        result_summary,
                        'Cleared stale step after parent goal reached a terminal state.'
                    )
                WHERE id IN ({placeholders})""",
            step_ids,
        )
        conn.execute(
            f"""UPDATE action_approval_queue
                SET status = 'expired',
                    resolved_at = COALESCE(resolved_at, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                WHERE step_id IN ({placeholders})
                  AND status IN ('pending', 'approved')""",
            step_ids,
        )
        conn.commit()
        return len(step_ids)


def _close_completed_progress_tasks(conn, lock, db_url: str) -> int:
    """Close active tasks whose own progress is complete and unblocked.

    Agents sometimes report ``progress_pct=100`` without following with a
    status update. Those rows remain active forever, consume capacity, and
    prevent lifecycle goal coverage from reaching newer work. Only close a
    task here when it has no active/pending goal plan; if a goal is still
    running, the goal rollup remains the source of truth.
    """
    try:
        rows = conn.execute(
            """SELECT t.id, t.title, t.agent_id
               FROM tasks t
               WHERE t.status IN ('open', 'in_progress', 'pending')
                 AND COALESCE(t.progress_pct, 0) >= 100
                 AND NOT EXISTS (
                     SELECT 1
                       FROM goal_plans gp
                      WHERE gp.parent_task_id = t.id
                        AND gp.status IN ('active', 'pending')
                 )""",
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.debug("Completed-progress task cleanup query failed: %s", exc)
        return 0

    if not rows:
        return 0

    task_ids = [int(row["id"]) for row in rows]

    # The writer's owner-action refusal, applied here too: this function marks
    # tasks 'done' with raw SQL and then cascades the same empty-result
    # delegation completion, so a guard in update_task() alone would leave
    # this path open. Measured 2026-10-06 (task #27694): a delegation went
    # 'completed' with result_summary = '' through exactly this cascade.
    try:
        from app.database import task_close_needs_result_reason

        refused = {
            task_id: task_close_needs_result_reason(conn, task_id)
            for task_id in task_ids
        }
        refused = {tid: why for tid, why in refused.items() if why}
    except Exception as exc:  # noqa: BLE001 - never let the guard kill the sweep
        log.warning("lifecycle sweep: owner-action result guard unavailable: %s", exc)
        refused = {}
    if refused:
        log.info(
            "Left %d owner-action/decision/deadline task(s) open instead of "
            "closing them with no recorded result: %s",
            len(refused),
            "; ".join(f"#{tid} ({why})" for tid, why in list(refused.items())[:5]),
        )
        task_ids = [tid for tid in task_ids if tid not in refused]
        rows = [row for row in rows if int(row["id"]) not in refused]
        if not task_ids:
            return 0

    now_expr = "strftime('%Y-%m-%dT%H:%M:%SZ', 'now')"
    task_columns = {
        str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
    }
    set_parts = ["status = 'done'", f"updated_at = {now_expr}"]
    if "completed_at" in task_columns:
        set_parts.append(f"completed_at = COALESCE(completed_at, {now_expr})")

    with lock:
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(
            f"""UPDATE tasks
                   SET {', '.join(set_parts)}
                 WHERE id IN ({placeholders})
                   AND status IN ('open', 'in_progress', 'pending')""",
            task_ids,
        )
        try:
            conn.execute(
                f"""UPDATE delegations
                       SET status = 'completed', completed_at = {now_expr}
                     WHERE task_id IN ({placeholders})
                       AND status = 'active'""",
                task_ids,
            )
        except Exception:
            pass
        conn.commit()

    closed_titles = [f"#{row['id']} {str(row['title'])[:80]}" for row in rows]
    try:
        from app.database import log_activity, vp_inbox_add

        log_activity(
            db_url,
            action="completed_progress_tasks_closed",
            detail=f"Closed {len(closed_titles)} active task(s) with progress_pct=100 and no active goal.",
            agent_id="lifecycle_sweep",
            details={"task_ids": task_ids},
        )
        body = (
            "Closed active tasks whose own progress was already 100% and which "
            "had no active/pending goal plan. This clears stale capacity without "
            "interrupting goal-backed work.\n\n"
            + "\n".join(closed_titles[:25])
        )
        if len(closed_titles) > 25:
            body += f"\n... and {len(closed_titles) - 25} more"
        vp_inbox_add(
            db_url,
            source="lifecycle_sweep",
            kind="fyi",
            title=f"Closed {len(closed_titles)} completed-progress active tasks",
            body=body,
            priority="p3",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Failed to record completed-progress cleanup: %s", exc)

    return len(task_ids)


def _sync_active_task_progress_from_goals(conn, lock, db_url: str) -> int:
    """Keep active parent task progress consistent with active goals.

    ``progress_pct=100`` on an active task means complete to humans and to
    capacity heuristics. If an active/pending child goal still exists, the goal
    is now the source of truth and task progress should stay below 100 until
    goal rollup closes the task.
    """
    try:
        rows = conn.execute(
            """SELECT t.id,
                      t.title,
                      COALESCE(MAX(gp.progress_pct), 0) AS goal_progress
                 FROM tasks t
                 JOIN goal_plans gp
                   ON gp.parent_task_id = t.id
                  AND gp.status IN ('active', 'pending')
                WHERE t.status IN ('open', 'in_progress', 'pending', 'blocked')
                  AND COALESCE(t.progress_pct, 0) >= 100
                GROUP BY t.id, t.title""",
        ).fetchall()
    except Exception as exc:  # noqa: BLE001
        log.debug("Active task progress sync query failed: %s", exc)
        return 0

    if not rows:
        return 0

    updates = [
        (max(0, min(95, int(row["goal_progress"] or 0))), int(row["id"]))
        for row in rows
    ]

    with lock:
        conn.executemany(
            """UPDATE tasks
                  SET progress_pct = ?,
                      updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                WHERE id = ?
                  AND status IN ('open', 'in_progress', 'pending', 'blocked')""",
            updates,
        )
        conn.commit()

    try:
        from app.database import log_activity

        log_activity(
            db_url,
            action="active_task_progress_synced",
            detail=f"Synced {len(updates)} active task(s) from active goal progress.",
            agent_id="lifecycle_sweep",
            details={
                "task_ids": [task_id for _progress, task_id in updates],
                "source": "active_goal_progress",
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Failed to record active task progress sync: %s", exc)

    return len(updates)


def _compute_work_order_next_run(
    wo: dict[str, Any],
    now: datetime,
) -> datetime:
    """Compute the next scheduled run for a standing work order.

    Mirrors ``work_orders._advance_schedule`` so released/stuck work
    orders fire at their real cadence instead of immediately re-running.
    """
    schedule_type = str(wo.get("schedule_type") or "interval")
    if schedule_type == "interval":
        minutes = int(wo.get("interval_minutes") or 60)
        return now + timedelta(minutes=minutes)
    if schedule_type == "daily":
        hour = int(wo.get("scheduled_hour") or 0)
        minute = int(wo.get("scheduled_minute") or 0)
        next_run = now.replace(
            hour=hour, minute=minute, second=0, microsecond=0
        )
        if next_run <= now:
            next_run += timedelta(days=1)
        return next_run
    if schedule_type == "cron":
        try:
            from croniter import croniter

            return croniter(
                str(wo.get("cron_expression") or "0 * * * *"), now
            ).get_next(datetime)
        except ImportError:
            return now + timedelta(days=1)
    return now + timedelta(hours=1)


def department_tick_cadence_minutes(conn, agent_id: str) -> float | None:
    """Median minutes between the agent's recent ticks, or None if unknown.

    `tick_telemetry` is the fleet's own record of when each agent actually ran,
    so this is the cadence the sweep has to live with rather than a guess. Fewer
    than `DEPARTMENT_CADENCE_MIN_SAMPLES` usable rows returns None, and the
    caller falls back to the documented fixed windows.
    """
    agent = str(agent_id or "").strip()
    if not agent:
        return None
    try:
        rows = conn.execute(
            """SELECT started_at FROM tick_telemetry
               WHERE agent_id = ? AND started_at IS NOT NULL
               ORDER BY started_at DESC
               LIMIT ?""",
            (agent, DEPARTMENT_CADENCE_SAMPLE),
        ).fetchall()
    except Exception as exc:  # noqa: BLE001 - telemetry must never stop a sweep
        log.debug("tick cadence unavailable for %s: %s", agent, exc)
        return None

    stamps: list[datetime] = []
    for row in rows:
        raw = row["started_at"] if hasattr(row, "keys") else row[0]
        parsed = _parse_iso_datetime(raw)
        if parsed is not None:
            stamps.append(parsed)
    if len(stamps) < DEPARTMENT_CADENCE_MIN_SAMPLES:
        return None
    stamps.sort()
    gaps = [
        (b - a).total_seconds() / 60.0
        for a, b in zip(stamps, stamps[1:])
        if (b - a).total_seconds() > 0
    ]
    if not gaps:
        return None
    gaps.sort()
    mid = len(gaps) // 2
    if len(gaps) % 2:
        return gaps[mid]
    return (gaps[mid - 1] + gaps[mid]) / 2.0


def goal_release_windows(conn, goal_id: str) -> tuple[float, float]:
    """(no_progress_minutes, progress_minutes) for releasing this goal.

    Both are floored at the documented constants, scaled by the goal's own
    department cadence, and capped. An unknown cadence returns the constants --
    the sweep never becomes *more* aggressive than it was before this change.
    """
    no_progress = float(STUCK_WORK_ORDER_MINUTES)
    progress = float(STUCK_WORK_ORDER_PROGRESS_WINDOW_MINUTES)
    agent = ""
    try:
        row = conn.execute(
            "SELECT assigned_agent FROM goal_plans WHERE id = ?", (goal_id,)
        ).fetchone()
        if row is not None:
            agent = str(
                (row["assigned_agent"] if hasattr(row, "keys") else row[0]) or ""
            )
    except Exception as exc:  # noqa: BLE001
        log.debug("goal agent lookup failed for %s: %s", goal_id, exc)
        return no_progress, progress

    cadence = department_tick_cadence_minutes(conn, agent)
    if cadence is None:
        return no_progress, progress
    no_progress = min(
        float(STUCK_WORK_ORDER_MAX_MINUTES),
        max(no_progress, cadence * STUCK_WORK_ORDER_CADENCE_MULTIPLIER),
    )
    progress = min(
        float(STUCK_PROGRESS_WINDOW_MAX_MINUTES),
        max(progress, cadence * STUCK_PROGRESS_WINDOW_CADENCE_MULTIPLIER),
    )
    return no_progress, progress


def _release_stuck_work_orders(conn, lock) -> int:
    """Mark standing_work_orders stuck in 'running' as 'failed' and
    bump next_run_after to now so the scheduler picks them back up.

    Work-order execution is asynchronous: creating the goal is fast, but
    finishing the spawned goal may take longer than the scheduler claim
    window. Only release executions whose spawned goal is missing,
    terminal, or stale beyond the normal stuck-goal window.
    """
    age = f"-{STUCK_WORK_ORDER_MINUTES} minutes"
    with lock:
        order_rows = conn.execute(
            """SELECT id, last_run_at FROM standing_work_orders
               WHERE last_run_status = 'running'
                 AND last_run_at IS NOT NULL
                 AND last_run_at < strftime(
                     '%Y-%m-%dT%H:%M:%S', 'now', ?
                 )""",
            (age,),
        ).fetchall()
        execution_rows = conn.execute(
            """SELECT id, work_order_id, goal_plan_id, started_at
               FROM work_order_executions
               WHERE status = 'running'
                 AND started_at IS NOT NULL
                 AND started_at < strftime(
                     '%Y-%m-%dT%H:%M:%S', 'now', ?
                 )""",
            (age,),
        ).fetchall()

        releasable_execution_rows = []
        protected_work_order_ids: set[str] = set()
        for row in execution_rows:
            goal_id = row["goal_plan_id"]
            if goal_id and _active_work_order_goal_is_recent(conn, goal_id):
                # Protect ONLY when there is live work: a step actually
                # claimed and currently 'running' with a fresh heartbeat
                # (or started recently). A completed/blocked/failed step
                # is NOT evidence of live work — a goal whose only
                # non-pending step is completed is finished or orphaned,
                # so its work order must be released or the scheduler
                # will never re-fire it at its real cadence.
                # (FIX 2026-08-30: previously any `status != 'pending'`
                # step protected the WO, so goals with completed=1 +
                # orphaned-running=1 stayed protected for up to 12h and
                # deadlocked hourly WOs like seed_home_sensors.)
                live_work = conn.execute(
                    """SELECT 1 FROM goal_steps
                       WHERE goal_id = ?
                         AND status = 'running'
                         AND (
                             (
                                 last_heartbeat_at IS NOT NULL
                                 AND datetime(last_heartbeat_at)
                                     >= datetime('now', ?)
                             )
                             OR
                             (
                                 last_heartbeat_at IS NULL
                                 AND started_at IS NOT NULL
                                 AND datetime(started_at)
                                     >= datetime('now', ?)
                             )
                         )
                       LIMIT 1""",
                    (
                        goal_id,
                        f"-{STALE_HEARTBEAT_MINUTES} minutes",
                        f"-{STALE_HEARTBEAT_MINUTES} minutes",
                    ),
                ).fetchone()
                if live_work:
                    protected_work_order_ids.add(row["work_order_id"])
                    continue

                # FIX (2026-08-31): Recent-progress protection. Between
                # agent turns ALL steps are 'pending' (nothing mid-flight),
                # so a progressing goal would fail the live_work check and
                # get released at 30 min even though its next step is simply
                # waiting for the agent's next turn (gaps of 20-71 min).
                # Protect when a step completed within the progress window;
                # genuinely dead goals (no completion for 90 min) still get
                # released at their cadence.
                #
                # 2026-10-02: both windows are now derived from THIS goal's
                # department cadence -- see `goal_release_windows`. The fixed
                # 30/90 min pair was shorter than the fleet's measured 60-90 min
                # turn cadence, so a healthy single-step-at-a-time goal was
                # released as "stuck" before its agent's next turn arrived.
                no_progress_minutes, progress_minutes = goal_release_windows(
                    conn, goal_id
                )
                execution_started = _parse_iso_datetime(row["started_at"])
                age_minutes = (
                    (datetime.now(timezone.utc) - execution_started).total_seconds()
                    / 60.0
                    if execution_started is not None
                    else None
                )
                if age_minutes is not None and age_minutes < no_progress_minutes:
                    protected_work_order_ids.add(row["work_order_id"])
                    log.info(
                        "Holding work order %s: goal %s is %d min old, inside its "
                        "%d min no-progress window (department cadence)",
                        row["work_order_id"],
                        goal_id,
                        int(age_minutes),
                        int(no_progress_minutes),
                    )
                    continue

                recent_progress = conn.execute(
                    """SELECT 1 FROM goal_steps
                       WHERE goal_id = ?
                         AND status = 'completed'
                         AND completed_at IS NOT NULL
                         AND datetime(completed_at)
                             >= datetime('now', ?)
                       LIMIT 1""",
                    (
                        goal_id,
                        f"-{int(progress_minutes)} minutes",
                    ),
                ).fetchone()
                if not recent_progress:
                    # A goal that has never completed a step is still protected
                    # by its own age: creation IS progress for a freshly spawned
                    # goal, and the department may not have had a turn yet.
                    goal_row = conn.execute(
                        "SELECT created_at FROM goal_plans WHERE id = ?",
                        (goal_id,),
                    ).fetchone()
                    created = _parse_iso_datetime(
                        goal_row["created_at"]
                        if goal_row is not None and hasattr(goal_row, "keys")
                        else (goal_row[0] if goal_row is not None else None)
                    )
                    if created is not None:
                        goal_age = (
                            datetime.now(timezone.utc) - created
                        ).total_seconds() / 60.0
                        if goal_age < progress_minutes:
                            recent_progress = True
                            log.info(
                                "Holding work order %s: goal %s is %d min old with "
                                "no step completed yet, inside its %d min progress "
                                "window",
                                row["work_order_id"],
                                goal_id,
                                int(goal_age),
                                int(progress_minutes),
                            )
                if recent_progress:
                    protected_work_order_ids.add(row["work_order_id"])
                    continue
            releasable_execution_rows.append(row)

        if not order_rows and not releasable_execution_rows:
            return 0

        order_ids = {
            row["id"]
            for row in order_rows
            if row["id"] not in protected_work_order_ids
        }
        order_ids.update(row["work_order_id"] for row in releasable_execution_rows)
        exec_ids = [row["id"] for row in releasable_execution_rows]
        goal_ids = [
            row["goal_plan_id"]
            for row in releasable_execution_rows
            if row["goal_plan_id"]
        ]

        if order_ids:
            # CRITICAL FIX (2026-08-08): Previously we set next_run_after
            # to NOW, which made every released work order due again on the
            # very next tick. Daily work orders therefore looped every
            # ~35 minutes, creating dozens of duplicate goals per day
            # (seed_ceo_review: 69 goals in 48h) and driving ~$20/day of
            # work-mode LLM spend. Now we advance the schedule per the
            # work order's own interval/daily/cron settings so a released
            # order fires again at its real cadence, not immediately.
            placeholders = ",".join("?" for _ in order_ids)
            full_rows = conn.execute(
                f"""SELECT * FROM standing_work_orders
                    WHERE id IN ({placeholders})""",
                tuple(order_ids),
            ).fetchall()
            now_dt = datetime.now(timezone.utc)
            for wo_row in full_rows:
                wo = dict(wo_row)
                try:
                    next_run = _compute_work_order_next_run(wo, now_dt)
                except Exception as exc:  # noqa: BLE001
                    log.debug(
                        "Schedule advance failed for WO %s: %s",
                        wo["id"],
                        exc,
                    )
                    next_run = now_dt + timedelta(hours=1)
                conn.execute(
                    """UPDATE standing_work_orders
                        SET last_run_status = 'failed',
                            next_run_after = ?
                        WHERE id = ?""",
                    (next_run.isoformat(), wo["id"]),
                )
            conn.commit()

        if exec_ids:
            placeholders = ",".join("?" for _ in exec_ids)
            conn.execute(
                f"""UPDATE work_order_executions
                    SET status = 'failed',
                        completed_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ', 'now'
                        ),
                        error_message = COALESCE(
                            error_message,
                            'Lifecycle sweep released stale running execution.'
                        )
                    WHERE id IN ({placeholders})""",
                exec_ids,
            )

        if goal_ids:
            placeholders = ",".join("?" for _ in goal_ids)
            terminal = ("completed", "cancelled", "failed")
            conn.execute(
                f"""UPDATE goal_steps
                    SET status = 'failed',
                        completed_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ', 'now'
                        ),
                        error_message = COALESCE(
                            error_message,
                            'Work order execution timed out.'
                        )
                    WHERE goal_id IN ({placeholders})
                      AND status NOT IN ({','.join('?' for _ in terminal)})""",
                (*goal_ids, *terminal),
            )
            conn.execute(
                f"""UPDATE goal_plans
                    SET status = 'failed',
                        completed_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ', 'now'
                        ),
                        updated_at = strftime(
                            '%Y-%m-%dT%H:%M:%fZ', 'now'
                        )
                    WHERE id IN ({placeholders})
                      AND status NOT IN ({','.join('?' for _ in terminal)})""",
                (*goal_ids, *terminal),
            )
        conn.commit()
        order_last_run_by_id = {row["id"]: row["last_run_at"] for row in order_rows}
        for wo_id in sorted(order_ids):
            log.warning(
                "Released stuck standing_work_order: id=%s last_run_at=%s",
                wo_id,
                order_last_run_by_id.get(wo_id),
            )
        for wo_id in sorted(protected_work_order_ids - order_ids):
            log.debug(
                "Kept running standing_work_order with recent active goal: id=%s last_run_at=%s",
                wo_id,
                order_last_run_by_id.get(wo_id),
            )
        for row in releasable_execution_rows:
            log.warning(
                "Released stale work_order_execution: id=%s work_order=%s",
                row["id"],
                row["work_order_id"],
            )
        return len(order_ids) + len(exec_ids)


def _sweep_row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a row that may be a minimal fixture without that column."""
    try:
        if key in row.keys():
            return row[key]
        return default
    except AttributeError:
        return default
    except (IndexError, KeyError, TypeError):
        return default


def _sweep_work_session_count(conn, task_id: int) -> int:
    """Work sessions ever recorded for this task, or -1 when unreadable.

    -1 is deliberately distinct from 0: "we could not read the history" must
    never be reported as "there is no history".
    """
    try:
        row = conn.execute(
            "SELECT COUNT(*) FROM work_sessions WHERE task_id = ?", (int(task_id),)
        ).fetchone()
        return int(row[0] or 0) if row else -1
    except Exception:  # noqa: BLE001
        return -1


def _sweep_close_note(conn, row: Any) -> tuple[str, list[str]]:
    """The honest reason a swept task is being closed, and what was missing."""
    sessions = _sweep_work_session_count(conn, int(row["id"]))
    missing: list[str] = []
    if sessions == 0:
        missing.append("no work session")
    elif sessions < 0:
        missing.append("work-session history unreadable")
    try:
        progress = int(_sweep_row_get(row, "progress_pct", 0) or 0)
    except (TypeError, ValueError):
        progress = 0
    if progress <= 0:
        missing.append("no progress recorded")
    missing.append("no completion artefact")
    reason = (
        f"auto-closed stale: no update for {STALE_TASK_DAYS} days and "
        + ", ".join(missing)
        + "; this close records that the timer gave up, not that the work was done"
    )
    return reason, missing


def _sweep_close_metadata(row: Any, reason: str, missing: list[str]) -> str:
    """`metadata_json` for a swept row, preserving whatever is already there."""
    raw = _sweep_row_get(row, "metadata_json", "{}")
    metadata: dict[str, Any] = {}
    if isinstance(raw, dict):
        metadata = dict(raw)
    elif raw:
        try:
            loaded = json.loads(str(raw))
            if isinstance(loaded, dict):
                metadata = loaded
        except (TypeError, ValueError):
            metadata = {}
    metadata["auto_close"] = {
        "state": "closed_without_evidence",
        "reason": reason,
        "missing": list(missing),
        "closed_by": "lifecycle_sweep",
        "stale_days": STALE_TASK_DAYS,
    }
    return json.dumps(metadata)


def _sweep_close_description(row: Any, reason: str) -> str:
    """`description` for a swept row, with the honest line appended."""
    existing = str(_sweep_row_get(row, "description", "") or "")
    marker = f"[lifecycle_sweep] {reason}"
    if marker in existing:
        return existing
    return f"{existing}\n{marker}".strip() if existing else marker


def _close_stale_tasks(conn, lock, db_url: str) -> int:
    """Auto-close stale tasks that are jamming the active-task ceiling.

    Targets:
    - in_progress tasks not updated in STALE_TASK_DAYS days
    - open tasks not updated in STALE_TASK_DAYS days (initiative_tick
      creates these; they never get acted on and accumulate against
      the ceiling)
    - approval-tagged tasks older than 4h (orphaned after their
      underlying approval queue entry expires)

    EXEMPT, closed by a human rather than by this timer:

    - anything recognisable as a customer's repair, and any customer-stall flag
      (see `customer_stall_watch`);
    - anything `app.services.task_protection.protection_reason` recognises as
      the OWNER's, having MONEY attached, carrying a DEADLINE, or explicitly
      REOPENED.

    That second exemption was added 2026-10-02 after the measured defect in
    journal D2907: over 2026-09-25..2026-10-02, 483 tasks were closed ``done``
    and 481 of them carry ``auto_close_evidence.state = "none"``. Age alone
    closed task 27097, the owner's own "check the credit card statements"
    instruction, without a statement ever being read, and 26485 "Pay NJ Dept of
    Labor 122.71" with no matching row in the ledger at any date. A timer may
    drain internal residue; it may not decide that the owner's money, deadline
    or request is finished. The marker set and the measurement behind each
    marker live in `app/services/task_protection.py` — not here — so this guard
    and the writer-level guard in `_task_close_would_be_a_lie` cannot drift
    apart.

    Every close this function still makes is stamped with the honest reason and
    what was missing: a swept row reads "auto-closed stale ... no work session,
    no progress, no artefact" instead of implying work happened. The stamp goes
    into ``metadata_json["auto_close"]`` (machine-readable) and is appended to
    ``description`` (readable by a human opening the task).

    Stale tasks accumulate against the active task ceiling and
    eventually jam the entire system: the create_task gate refuses
    new work because active >= ceiling. Closing them with a clear note
    keeps the pipeline moving. Operators can re-open or re-create if a
    task was prematurely closed.

    Also files a VP inbox entry whenever any tasks are closed so the
    owner can audit on the next session.
    """
    age = f"-{STALE_TASK_DAYS} days"
    # `SELECT t.*` rather than a column list: the customer-work test below needs
    # title/description/tags_json/metadata_json, and minimal fixtures in this
    # repo's tests do not create every column. Missing columns are tolerated.
    rows = conn.execute(
        """SELECT t.*
           FROM tasks t
           WHERE t.status IN ('in_progress', 'open')
             AND t.updated_at < strftime(
                 '%Y-%m-%dT%H:%M:%S', 'now', ?)""",
        (age,),
    ).fetchall()

    # Also close approval-tagged tasks older than STALE_APPROVAL_TASK_HOURS.
    # Their underlying approval queue entry expires after 2h
    # (STALE_APPROVAL_HOURS), so the task itself becomes orphaned and just
    # consumes ceiling slots.
    #
    # 2026-10-26, two defects measured on the authority and fixed here:
    #   1. `status IN ('in_progress','pending','blocked')` matched **zero** rows
    #      -- every approval task this company creates is status 'open' -- so this
    #      branch had never closed a single one, and 108 were sitting against a
    #      300-task ceiling.
    #   2. The 4h window was chosen when the only approvals were the 2h queue's
    #      orphans. Too short to be answerable in a working day; 48h is long
    #      enough to be seen and short enough that the queue cannot become a
    #      dumping ground. Dedupe means at most one open approval per (action,
    #      agent, resource), so nothing repopulates it.
    approval_rows = conn.execute(
        f"""SELECT t.*
           FROM tasks t
                     WHERE t.status IN ('open', 'in_progress', 'pending', 'blocked')
                         AND (t.tags_json LIKE '%"approval"%'
                              OR t.title LIKE 'APPROVAL:%'
                              OR t.title LIKE 'Approve action:%')
             AND t.created_at < strftime(
                 '%Y-%m-%dT%H:%M:%S', 'now', ?)""",
        (f"-{STALE_APPROVAL_TASK_HOURS} hours",),
    ).fetchall()

    all_rows = list(rows) + [
        r for r in approval_rows if r["id"] not in {x["id"] for x in rows}
    ]

    # A customer repair is NEVER auto-closed by a timer.
    #
    # `'in_progress'` (underscore) is one keystroke from `'in-progress'`
    # (hyphen) -- the spelling that currently hides #3132, #4467 and #4485 from
    # this filter, and the only spelling those three rows use. If a customer job
    # ever lands in the underscore spelling, this reaper would mark a device that
    # is physically in the shop as `done` after 7 days and destroy the only
    # record that the customer is waiting. Recognisable customer work is left for
    # a human to close; customer_stall_watch flags it instead of hiding it.
    #
    # The stall watch's own flags are protected too: they are the one surface
    # that says "this customer job has been forgotten", and closing them after 7
    # days would re-bury the exact thing the watch exists to surface.
    try:
        from app.services.customer_stall_watch import (
            is_stall_flag,
            looks_like_customer_work,
        )

        protected = [
            r["id"]
            for r in all_rows
            if looks_like_customer_work(r) or is_stall_flag(r)
        ]
    except Exception as exc:  # noqa: BLE001 - never let the guard kill the reaper
        log.warning("lifecycle sweep: customer auto-close guard unavailable: %s", exc)
        protected = []
    if protected:
        log.info(
            "Left %d customer task(s)/stall flag(s) open for a human instead of "
            "auto-closing: %s",
            len(protected),
            ", ".join(f"#{tid}" for tid in protected[:10]),
        )
        all_rows = [r for r in all_rows if r["id"] not in set(protected)]

    # The owner's work is NEVER auto-closed by a timer either.
    #
    # Measured 2026-10-02 (journal D2907): age alone closed 27097 -- the owner's
    # own "check the credit card statements" instruction -- and 26485, "Pay NJ
    # Dept of Labor 122.71", with no matching ledger row at any date. Nothing
    # here exempted an owner ask, a money item or a deadline. See
    # `app/services/task_protection.py` for the marker set and the measurement
    # that justifies each marker (including the two words measured OUT of the
    # money test because they fired on the recurring internal chores this
    # reaper exists to drain).
    try:
        from app.services.task_protection import protection_reason

        exempt = {r["id"]: protection_reason(r) for r in all_rows}
        exempt = {tid: why for tid, why in exempt.items() if why}
    except Exception as exc:  # noqa: BLE001 - never let the guard kill the reaper
        log.warning("lifecycle sweep: owner/money/deadline guard unavailable: %s", exc)
        exempt = {}
    if exempt:
        log.info(
            "Left %d owner/money/deadline task(s) open for a human instead of "
            "auto-closing: %s",
            len(exempt),
            "; ".join(f"#{tid} ({why})" for tid, why in list(exempt.items())[:5]),
        )
        all_rows = [r for r in all_rows if r["id"] not in exempt]

    if not all_rows:
        return 0

    # Which columns this table actually has. Minimal test fixtures in this repo
    # create a subset of `tasks`; a missing column must mean "leave it alone",
    # never an exception that stops the reaper from draining anything at all.
    try:
        task_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(tasks)").fetchall()
        }
    except Exception:  # noqa: BLE001
        task_columns = {"status", "updated_at"}

    closed_titles: list[str] = []
    with lock:
        for row in all_rows:
            try:
                reason, missing = _sweep_close_note(conn, row)
                updates = [
                    "status = 'done'",
                    "updated_at = strftime('%Y-%m-%dT%H:%M:%S', 'now')",
                ]
                params: list[Any] = []

                if "metadata_json" in task_columns:
                    updates.append("metadata_json = ?")
                    params.append(_sweep_close_metadata(row, reason, missing))
                if "description" in task_columns:
                    updates.append("description = ?")
                    params.append(_sweep_close_description(row, reason))

                params.append(row["id"])
                conn.execute(
                    f"UPDATE tasks SET {', '.join(updates)} WHERE id = ?",
                    params,
                )
                # A swept close is NOT a completion, so `completed_at` is left
                # alone: NULL there is the honest signature of "no work was
                # ever recorded", and setting it would manufacture one.
                closed_titles.append(f"#{row['id']} {row['title'][:60]} -- {reason}")
            except Exception as exc:  # noqa: BLE001
                log.debug("Failed to auto-close task %s: %s", row["id"], exc)
        conn.commit()

    if not closed_titles:
        return 0

    log.info(
        "Auto-closed %d stale tasks "
        "(>%d days old: in_progress+open, or expired approvals)",
        len(closed_titles),
        STALE_TASK_DAYS,
    )

    # File a VP inbox entry summarising what was closed.
    try:
        from app.database import vp_inbox_add

        body = (
            "Auto-closed by lifecycle sweep. Covers in_progress+open "
            "tasks older than %d days, plus approval-tagged tasks "
            "older than 4h. Re-open if still relevant. Customer repairs and "
            "customer-stall flags are exempt and were left open for a human, as "
            "are tasks that are the owner's, carry money or a deadline, or were "
            "explicitly reopened. Each line below states what was missing when "
            "it was closed -- none of these closes is evidence that the work "
            "was done."
            "\n\n" + "\n".join(line[:160] for line in closed_titles[:25])
        ) % STALE_TASK_DAYS
        if len(closed_titles) > 25:
            body += f"\n... and {len(closed_titles) - 25} more"
        vp_inbox_add(
            db_url,
            source="lifecycle_sweep",
            kind="fyi",
            title=(f"Auto-closed {len(closed_titles)} stale in_progress tasks"),
            body=body,
            priority="p3",
        )
    except Exception as exc:  # noqa: BLE001
        log.debug("Failed to file VP inbox entry: %s", exc)

    return len(closed_titles)


def _release_stale_claims(conn, lock) -> int:
    """Phase 1: Release steps claimed but heartbeat expired."""
    with lock:
        rows = conn.execute(
            """SELECT id, goal_id, claimed_by, attempts, max_retries
               FROM goal_steps
               WHERE status = 'running'
                 AND (
                     (
                         last_heartbeat_at IS NOT NULL
                         AND datetime(last_heartbeat_at) < datetime('now', ?)
                     )
                     OR (
                         last_heartbeat_at IS NULL
                         AND started_at IS NOT NULL
                         AND datetime(started_at) < datetime('now', ?)
                     )
                 )""",
            (
                f"-{STALE_HEARTBEAT_MINUTES} minutes",
                f"-{STALE_HEARTBEAT_MINUTES} minutes",
            ),
        ).fetchall()

        released = 0
        for row in rows:
            step_id, goal_id, claimed_by, attempts, max_retries = row
            attempts = attempts or 0
            max_retries = max_retries or MAX_RETRIES
            new_status = "pending" if attempts < max_retries else "failed"

            conn.execute(
                """UPDATE goal_steps
                   SET status = ?, claimed_by = NULL,
                       last_heartbeat_at = NULL
                   WHERE id = ?""",
                (new_status, step_id),
            )
            released += 1
            log.info(
                "Released stale claim: step=%s goal=%s agent=%s → %s",
                step_id,
                goal_id,
                claimed_by,
                new_status,
            )
        if released:
            conn.commit()
    return released


def _retry_failed_steps(conn, lock) -> int:
    """Phase 2: Re-queue failed steps whose backoff window has elapsed."""
    with lock:
        rows = conn.execute(
            """SELECT id, attempts, max_retries, completed_at
               FROM goal_steps
               WHERE status = 'failed'
                 AND attempts < max_retries""",
        ).fetchall()

        retried = 0
        now = time.time()
        for row in rows:
            step_id, attempts, max_retries, completed_at = row
            attempts = attempts or 0
            max_retries = max_retries or MAX_RETRIES

            if attempts >= max_retries:
                continue

            # Check backoff window
            delay = _backoff_delay(attempts)
            if completed_at:
                try:
                    import datetime as _dt

                    fail_time = _dt.datetime.fromisoformat(completed_at)
                    elapsed = now - fail_time.timestamp()
                    if elapsed < delay:
                        continue
                except (ValueError, TypeError):
                    pass

            conn.execute(
                """UPDATE goal_steps
                   SET status = 'pending', claimed_by = NULL,
                       error_message = NULL
                   WHERE id = ?""",
                (step_id,),
            )
            retried += 1
            log.info(
                "Retry scheduled: step=%s attempt=%d/%d delay=%.0fs",
                step_id,
                attempts + 1,
                max_retries,
                delay,
            )
        if retried:
            conn.commit()
    return retried


def _reopen_stale_blocked_steps(conn, lock) -> int:
    """Phase 2b: Reopen blocked steps in ACTIVE goals after a cooldown.

    ``blocked`` is otherwise a dead-end status: claim_next_step re-claims
    it after RELEASED_STEP_COOLDOWN_MINUTES, but _should_skip_step
    Check 4 (attempts >= threshold + stale meta-only error) instantly
    re-blocks it — so the step NEVER gets a real LLM call. When the
    blocking root cause has been fixed (e.g. the empty-tool-name bug),
    these steps can succeed if actually retried.

    Reopened steps get attempts=0 + error_message=NULL so the pre-flight
    skip checks no longer fire. A reopen counter is persisted in
    output_json.reopened_count and capped at BLOCKED_REOPEN_MAX so
    genuinely-unworkable steps don't churn LLM budget forever.
    """
    with lock:
        cutoff = (
            datetime.now(timezone.utc) - timedelta(hours=BLOCKED_REOPEN_HOURS)
        ).isoformat()
        rows = conn.execute(
            """SELECT gs.id, gs.output_json, gp.status AS goal_status
               FROM goal_steps gs
               JOIN goal_plans gp ON gp.id = gs.goal_id
               WHERE gs.status = 'blocked'
                 AND gp.status = 'active'
                 AND gs.completed_at IS NOT NULL
                 AND gs.completed_at < ?
                 AND (
                     gs.error_message LIKE '%meta-only%'
                     OR gs.error_message LIKE '%did not complete%'
                     OR gs.error_message LIKE '%already attempted%'
                 )
               ORDER BY gs.completed_at ASC""",
            (cutoff,),
        ).fetchall()

        reopened = 0
        for row in rows:
            step_id = row["id"]
            try:
                output = json.loads(row["output_json"] or "{}")
                if not isinstance(output, dict):
                    output = {}
            except (ValueError, TypeError):
                output = {}
            reopened_count = int(output.get("reopened_count", 0) or 0)
            if reopened_count >= BLOCKED_REOPEN_MAX:
                continue

            output["reopened_count"] = reopened_count + 1
            output["reopened_at"] = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """UPDATE goal_steps
                   SET status = 'pending',
                       claimed_by = NULL,
                       started_at = NULL,
                       completed_at = NULL,
                       attempts = 0,
                       error_message = NULL,
                       output_json = ?
                   WHERE id = ?""",
                (json.dumps(output), step_id),
            )
            reopened += 1
            log.info(
                "Reopened stale blocked step=%s (reopen #%d, cap %d)",
                step_id,
                reopened_count + 1,
                BLOCKED_REOPEN_MAX,
            )

        if reopened:
            conn.commit()
    return reopened


def _rollup_completed_goals(conn, lock, db_url: str | None = None) -> int:
    """Phase 3: Complete goals where all steps are done."""
    with lock:
        goal_columns = {
            str(row[1])
            for row in conn.execute("PRAGMA table_info(goal_plans)").fetchall()
        }
        goal_source_expr = "gp.source" if "source" in goal_columns else "''"
        parent_task_expr = (
            "gp.parent_task_id" if "parent_task_id" in goal_columns else "NULL"
        )
        goals = conn.execute(
            f"""SELECT gp.id, gp.title, {goal_source_expr} AS source,
                      {parent_task_expr} AS parent_task_id
               FROM goal_plans gp
               WHERE gp.status = 'active'
                 AND NOT EXISTS (
                     SELECT 1 FROM goal_steps gs
                     WHERE gs.goal_id = gp.id
                       AND gs.status NOT IN ('completed', 'skipped')
                 )
                 AND EXISTS (
                     SELECT 1 FROM goal_steps gs2
                     WHERE gs2.goal_id = gp.id
                 )""",
        ).fetchall()

        completed = 0
        completed_goals = []
        for goal in goals:
            goal_id = goal["id"]
            title = goal["title"]
            conn.execute(
                """UPDATE goal_plans
                   SET status = 'completed', progress_pct = 100,
                       completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE id = ?""",
                (goal_id,),
            )
            completed_goals.append(dict(goal))
            completed += 1
            log.info("Goal auto-completed: %s (%s)", goal_id, title)

        if completed:
            conn.commit()

    for goal in completed_goals:
        parent_task_id = goal.get("parent_task_id")
        if parent_task_id and db_url:
            try:
                from app.database import update_task

                update_task(db_url, int(parent_task_id), status="done")
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to close parent task for goal %s: %s",
                    goal["id"],
                    exc,
                )

        if goal.get("source") == "standing_work_order" and db_url:
            try:
                from app.services.work_orders import (
                    complete_work_order_execution,
                )

                complete_work_order_execution(
                    db_url=db_url,
                    goal_plan_id=goal["id"],
                    success=True,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning(
                    "Failed to complete work order for goal %s: %s",
                    goal["id"],
                    exc,
                )
    return completed


def _detect_stuck_goals(conn, lock, db_url: str) -> int:
    """Phase 4: Escalate goals with no progress for > STUCK_GOAL_HOURS.

    CRITICAL FIX (2026-08-09): Previously every stuck goal re-escalated
    every _P2_COOLDOWN_SEC (6h) FOREVER — the escalation router dedups only
    within a single cooldown window, so a goal stuck for 68 days fired 156
    escalations and the activity log accumulated 16,575 `escalation_p2`
    entries all-time. Now each goal escalates at most once per 24h, and a
    goal that has already been escalated >= ESCALATION_DIE_THRESHOLD times
    is auto-cancelled instead of escalating again — stuck goals die instead
    of screaming forever.
    """
    with lock:
        goals = conn.execute(
            """SELECT gp.id, gp.title, gp.assigned_agent, gp.updated_at
               FROM goal_plans gp
               WHERE gp.status = 'active'
                 AND gp.updated_at < strftime(
                     '%Y-%m-%dT%H:%M:%S', 'now', ?
                 )""",
            (f"-{STUCK_GOAL_HOURS} hours",),
        ).fetchall()

    escalated = 0
    auto_cancelled = 0
    for goal_id, title, agent_id, _updated_at in goals:
        try:
            from app.services.escalation_router import (
                route_escalation,
                severity_for_class,
            )

            # Count how many times this goal has already been escalated
            # (all-time). Use it to decide: escalate, wait, or auto-cancel.
            prior = conn.execute(
                """SELECT COUNT(*) AS c FROM activity_log
                   WHERE action = 'escalation_p2'
                     AND detail LIKE ?""",
                (f"%goal={goal_id} %",),
            ).fetchone()["c"]

            if prior >= ESCALATION_DIE_THRESHOLD:
                # Escalated too many times with no resolution — kill the
                # goal so it stops re-escalating. It can be re-created by
                # its standing work order on the next scheduled fire.
                with lock:
                    conn.execute(
                        """UPDATE goal_plans
                           SET status = 'cancelled',
                               completed_at = strftime(
                                   '%Y-%m-%dT%H:%M:%SZ', 'now'
                               ),
                               updated_at = strftime(
                                   '%Y-%m-%dT%H:%M:%SZ', 'now'
                               )
                           WHERE id = ? AND status = 'active'""",
                        (goal_id,),
                    )
                    conn.execute(
                        """UPDATE goal_steps
                           SET status = 'skipped',
                               completed_at = strftime(
                                   '%Y-%m-%dT%H:%M:%SZ', 'now'
                               ),
                               error_message = (
                                   'Auto-cancelled: stuck > %dh after '
                                   'multiple escalations.'
                               )
                           WHERE goal_id = ?
                             AND status NOT IN (
                                 'completed', 'failed', 'skipped'
                             )""",
                        (STUCK_GOAL_HOURS, goal_id),
                    )
                    conn.commit()
                auto_cancelled += 1
                continue

            severity = severity_for_class("functional")  # P2
            action = route_escalation(
                severity=severity,
                agent_id=agent_id or "unknown",
                error_text=f"Goal stuck > {STUCK_GOAL_HOURS}h: {title}",
                goal_id=goal_id,
                db_url=db_url,
            )
            if action != "suppressed":
                escalated += 1
        except Exception:  # noqa: BLE001
            log.debug("Failed to escalate stuck goal %s", goal_id)

    if auto_cancelled:
        log.warning(
            "Auto-cancelled %d stuck goal(s) that exceeded escalation cap",
            auto_cancelled,
        )
    return escalated + auto_cancelled


def _cleanup_superseded(conn, lock) -> int:
    """Phase 5: Cancel active goals that have been superseded."""
    with lock:
        rows = conn.execute(
            """SELECT id FROM goal_plans
               WHERE status = 'active'
                 AND superseded_by IS NOT NULL""",
        ).fetchall()

        cancelled = 0
        for (goal_id,) in rows:
            step_rows = conn.execute(
                """
                SELECT id FROM goal_steps
                WHERE goal_id = ?
                  AND status IN (
                      'pending',
                      'blocked',
                      'running',
                      'waiting_approval',
                      'suspended'
                  )
                """,
                (goal_id,),
            ).fetchall()
            step_ids = [int(row[0]) for row in step_rows]

            conn.execute(
                """UPDATE goal_plans
                   SET status = 'cancelled',
                       updated_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE id = ?""",
                (goal_id,),
            )

            if step_ids:
                placeholders = ", ".join("?" for _ in step_ids)
                conn.execute(
                    f"""
                    UPDATE goal_steps
                    SET status = 'skipped',
                        claimed_by = NULL,
                        started_at = NULL,
                        completed_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now'),
                        result_summary = ?,
                        output_json = ?
                    WHERE id IN ({placeholders})
                    """,
                    (
                        "Skipped because the goal was superseded.",
                        json.dumps(
                            {
                                "action": "skip",
                                "reason": "goal_superseded",
                            }
                        ),
                        *step_ids,
                    ),
                )
                conn.execute(
                    f"""
                    UPDATE action_approval_queue
                    SET status = 'expired',
                        resolved_at = strftime('%Y-%m-%dT%H:%M:%SZ', 'now')
                    WHERE step_id IN ({placeholders})
                      AND status IN ('pending', 'approved')
                    """,
                    tuple(step_ids),
                )

            cancelled += 1
            log.info("Cancelled superseded goal: %s", goal_id)

        if cancelled:
            conn.commit()
    return cancelled


def _expire_stale_approvals(conn, lock) -> int:
    """Expire pending approvals older than STALE_APPROVAL_HOURS.

    Stale approvals block agent steps indefinitely. Expiring them and
    auto-promoting the action to autonomous ensures work progresses
    rather than looping through the approval queue forever.
    """
    age = f"-{STALE_APPROVAL_HOURS} hours"
    rows = conn.execute(
        """SELECT id, step_id, tool_name FROM action_approval_queue
           WHERE status = 'pending'
             AND created_at < strftime(
                 '%Y-%m-%dT%H:%M:%SZ', 'now', ?)""",
        (age,),
    ).fetchall()

    if not rows:
        return 0

    expired = 0
    promoted_actions: set[str] = set()
    with lock:
        for row in rows:
            conn.execute(
                """UPDATE action_approval_queue
                   SET status = 'expired',
                       resolved_at = strftime(
                           '%Y-%m-%dT%H:%M:%SZ', 'now')
                   WHERE id = ?""",
                (row["id"],),
            )
            # Reset the suspended step so it can be retried
            if row["step_id"]:
                conn.execute(
                    """UPDATE goal_steps
                       SET status = 'pending',
                           claimed_by = NULL,
                           started_at = NULL
                       WHERE id = ?
                         AND status IN (
                             'waiting_approval',
                             'suspended',
                             'blocked'
                         )""",
                    (row["step_id"],),
                )
            # Track which actions need auto-promotion
            tool = row["tool_name"] if "tool_name" in row.keys() else None
            if tool:
                promoted_actions.add(tool)
            expired += 1
        conn.commit()

    # An expiry GRANTS NOTHING (2026-10-26).
    #
    # This block used to promote every action whose approval expired to L4 --
    # `_level_overrides[action_name] = max(default, 4)` -- so "the owner did not
    # answer in two hours" resolved to "then run it anyway". Measured on the
    # authority: 1288 queue entries had been expired, i.e. 1288 silent grants,
    # and it is why an action kept reappearing at L4 after being demoted. A
    # timeout is not consent, and an autonomy gate that grants on timeout cannot
    # be trusted to say no.
    #
    # The trade: an expired request can be re-asked, so a gated step may return
    # here every two hours. That treadmill is bounded (one row per (agent, tool,
    # step) per cycle), visible in this queue, and vastly preferable to granting
    # execution because nobody was watching. If it proves noisy, the next
    # refinement is a repeat-expiry counter that parks the step as blocked.
    if expired:
        log.info(
            "Expired %d stale pending approvals (>%dh old), granted nothing",
            expired,
            STALE_APPROVAL_HOURS,
        )
        return expired

    return expired
