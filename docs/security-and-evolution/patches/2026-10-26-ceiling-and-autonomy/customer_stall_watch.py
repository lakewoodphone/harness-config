"""Customer Stall Watch — make a forgotten customer repair surface itself.

THE DEFECT (measured read-only on the live database, 2026-09-15)
---------------------------------------------------------------
Three real customer repairs were sitting in ``tasks`` with no update since
June, invisible to every report:

    id    status       created              updated              progress
    3132  in-progress  2026-06-01 18:48     2026-06-01 19:03     0%
    4467  in-progress  2026-06-23 17:41     2026-06-23 17:41     0%
    4485  in-progress  2026-06-25 18:10     2026-06-25 18:10     50%

#3132's note says the battery was due 2026-06-03; #4467's says the lens was
due 2026-07-05..15; #4485's says "copy in progress ... hand off to customer".
82 to 106 days later nothing had moved them and nothing had noticed.

Three independent reasons nothing noticed, each verified against the live rows:

1. ``status='in-progress'`` (hyphen) is not in ``_close_stale_tasks``'s filter
   ``status IN ('in_progress','open')``. Measured: the hyphen spelling matches
   exactly three rows in the whole 25,405-row table, and they are #3132, #4467
   and #4485. The one status the forgotten customer jobs landed in is the one
   status the existing reaper cannot see.
2. ``staleness_detector._flag_stale_tasks`` looks only at ``status='open'``,
   takes at most 20 rows, and -- this is the part that makes it worse than
   useless -- writes ``updated_at = now`` while appending its "stale" marker.
   It resets the very clock it is measuring, then skips the row forever because
   the marker is now in the description.
3. Nothing in the system asked "is this a customer's job?". The ``"lpt"`` tag
   that was supposed to answer that is present on 2 of the 11 live customer
   jobs; #4467 and #4485, the worst two, have no tag at all.

WHAT THIS MODULE DOES
---------------------
Detects customer-facing tasks that are still active but have not been touched
for longer than a threshold, and escalates each stalled *episode* exactly once
per re-alert window to surfaces a human reads: a task in the tracker, a VP
inbox row, an ``activity_log`` line (via the P2 escalation router), and a
``customer_stall`` field stamped into the task's own ``metadata_json`` that any
owner-facing digest can read.

WHAT IT MUST NEVER DO
---------------------
Send anything to anyone. There is no call to SMS, email, voice or any other
outbound path in this module -- it drafts and flags only. AGENTS.md is
explicit: no outbound email, SMS or call without an explicit per-message owner
approval in the current conversation.

It also does not copy task descriptions into the tables it writes. #4485's
description holds a live customer's data-recovery detail ("8 dead boot sectors
... 273 GB data"); echoing that into a new table would spread the exposure
instead of fixing the problem. Alerts carry the task id and title only --
both already exist in ``tasks``.

IDEMPOTENCE
-----------
A stall *episode* is (task_id, the task's ``updated_at`` at first detection),
and ``ux_customer_stall_episode`` is a UNIQUE index on exactly that pair. Every
detection is an ``INSERT OR IGNORE``, so the database -- not this module's
bookkeeping -- is what guarantees that running the watch hourly cannot produce
a second alert for the same stalled job. If the job later moves, ``updated_at``
changes, the next stall is a new episode, and a new alert is correct.

The module never writes ``tasks.updated_at``. A watcher that stamps "I looked
at this" onto the field it measures is how the defect in
``staleness_detector._flag_stale_tasks`` happened; see above.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from typing import Any

log = logging.getLogger(__name__)

STALL_SOURCE = "customer_stall_watch"
STALL_TABLE = "customer_stall_alerts"

# ── Thresholds ────────────────────────────────────────────────────────
# Default days of NO UPDATE before a customer job is treated as stalled.
#
# 21 days is measured, not chosen for looks. On the live table the declared
# waits on real customer jobs run from 2 days (#3132, "free 2-day delivery est.
# Jun 3") to the widest AliExpress estimate in the corpus, 3 weeks (#4467,
# "Est. delivery Jul 5-15" on an order placed Jun 23). 21 days is therefore
# longer than every wait any live customer job has actually declared, so a job
# that wrote down its own deadline is not flagged before that deadline passes
# -- and it is still less than a quarter of the 82-106 days these three jobs
# actually sat unread.
#
# It is a constant, and that is the honest choice rather than the clever one:
# the only per-task clock available is the ETA written in free prose inside
# `description`, and there is no reliable way to read those. The two real cases
# contradict any naive parse ("est. Jun 3" vs "Est. delivery Jul 5-15"), the
# system has never recorded when a part actually arrived, and a threshold that
# quietly misreads a date would produce alerts nobody trusts. So the clock is
# the one field the tracker does maintain -- `updated_at` -- with a constant
# that no observed wait can trip early. A *declared* wait, i.e. one the
# operator wrote into the status itself, gets the longer clock below.
STALL_DAYS_SILENT_DEFAULT = 21

# A status that itself says "we are waiting" is not silence, so it earns a
# longer clock before it becomes a stall. It is still not immortal: a customer
# repair on hold for a month with nothing written down is money on the shelf.
STALL_DAYS_DECLARED_WAIT_DEFAULT = 30

# A stall that keeps stalling must re-nag, or the one alert becomes a mute
# alarm. Once a week is a nag; once an hour is spam.
RE_ALERT_DAYS_DEFAULT = 7

ENV_SILENT_DAYS = "CUSTOMER_STALL_SILENT_DAYS"
ENV_DECLARED_WAIT_DAYS = "CUSTOMER_STALL_DECLARED_WAIT_DAYS"
ENV_RE_ALERT_DAYS = "CUSTOMER_STALL_REALERT_DAYS"
ENV_ENABLED = "CUSTOMER_STALL_WATCH_ENABLED"

# The threshold values live in environment variables rather than app/config.py
# because this branch was scoped away from config.py. See the handoff note:
# hoisting them into Settings is a one-line follow-up for whoever owns it.

# ── "Waiting, and we know why" ────────────────────────────────────────
# Statuses in which the operator has *written down* that the job is waiting on
# something outside their control. A declared wait is not silence, which is the
# distinction that matters: "in-progress and nothing has happened for 82 days"
# is a forgotten job, "awaiting_part and the note says which part" is a tracked
# one.
#
# `blocked` is deliberately NOT here. All nine live `blocked` tasks are internal
# workflow residue (initiative ticks, work orders) and `blocked` is the goal
# engine's dead-end state, not a statement about a customer.
DECLARED_WAIT_STATUSES = frozenset(
    {
        "awaiting_part",
        "waiting_on_customer",
        "waiting on customer",
        "awaiting_customer",
        "on_hold",
        "on hold",
        "paused",
    }
)

# ── What makes a task customer-facing ─────────────────────────────────
# Chosen by measurement over all 25,405 live rows, cross-checked against the 11
# live customer jobs and the 41 live non-terminal internal ones.
LPT_TAG = "lpt"
# The tag this module puts on the flags it creates. Used to keep a flag about a
# customer job from being mistaken for a customer job (see `customer_markers`),
# and to keep the 7-day stale-task reaper from closing a flag nobody has read.
STALL_FLAG_TAG = "customer-stall"
_TITLE_INTAKE_RE = re.compile(r"^\s*(?:repair\s*:|lpt\s+customer\b)", re.IGNORECASE)
_CUSTOMER_WORD_RE = re.compile(r"\bcustomers?\b", re.IGNORECASE)
_HUB_CASE_PATH = "lpt-hub/docs/customer-operations"
_PHONE_RE = re.compile(
    r"(?:\+?1[\s.\-]?)?\(?\d{3}\)?[\s.\-]?\d{3}[\s.\-]?\d{4}\b"
)


def _row_get(row: Any, key: str, default: Any = None) -> Any:
    """Read `key` from a sqlite3.Row, a dict, or a partial fixture row."""
    try:
        keys = row.keys()
    except AttributeError:
        keys = ()
    if keys:
        return row[key] if key in keys else default
    if isinstance(row, dict):
        return row.get(key, default)
    return default


def _decode_json(raw: Any, fallback: Any) -> Any:
    if raw is None or raw == "":
        return fallback
    if isinstance(raw, (list, dict)):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, ValueError):
        return fallback


def customer_markers(row: Any) -> list[str]:
    """Which LPT-intake markers say this row is a customer's job.

    Returns the marker names that fired (an audit trail for the alert), or an
    empty list when the row is not recognisably customer work.

    Every marker is something the customer-intake path writes and the internal
    generators (initiative ticks, work orders, health checks) never do:

    ``lpt_tag``
        ``"lpt"`` in ``tags_json``. Explicit, and alone it is not enough: it is
        present on only 2 of the 11 live customer jobs, and both of the worst
        cases (#4467, #4485) have no tag at all.
    ``repair_title``
        The title opens ``Repair:`` (with the colon). 67 live rows match and
        every one of them is a customer job. The internal
        ``Repair boa_sync (114 consecutive failures) ...`` (#25299) does not
        match, because it has no colon. This is the marker that catches #4485,
        whose description contains no customer word at all -- only "hand off to
        customer" at the very end.
    ``customer_word``
        ``customer``/``customers`` as a word in the title or description.
        Catches #2444 (the customer is named only in the title) and #3495 (named
        mid-description, after a serial number).
    ``hub_case_path``
        An ``lpt-hub/docs/customer-operations`` path in ``metadata_json`` --
        the case-file pointer the intake writes (#2899).

    A **phone number was evaluated and rejected** as a marker. Measured over
    the 52 live non-terminal tasks it fires on exactly one row, #25167, which
    is the owner's own house line being ported to magicJack -- a false positive
    -- and it adds no true customer row, because every live customer job
    already carries one of the four markers above. Removing it makes the alert
    set smaller and truer, which is the trade this module is supposed to make.

    A row carrying ``STALL_FLAG_TAG`` is **never** customer work. That is not a
    loophole, it is the same distinction the whole module is built on: a flag
    *about* a customer's job is not the customer's job. Measured by running the
    watch twice on the live rows: without this exclusion the second run counted
    22 customer tasks instead of 11, because each flag task's own title says
    "CUSTOMER STALL" and its body lists the markers -- and in 21 days those flag
    tasks would have been flagged as stalled customer work by this very watch.
    """
    markers: list[str] = []

    tags = _decode_json(_row_get(row, "tags_json", "[]"), [])
    lowered: set[str] = set()
    if isinstance(tags, (list, tuple)):
        lowered = {str(tag).strip().lower() for tag in tags}
    if STALL_FLAG_TAG in lowered:
        return []
    # An APPROVAL REQUEST is never a customer's job (2026-10-26).
    #
    # Measured on the authority: of the 164 tasks past the 7-day stale-task
    # window, 160 fired `customer_word` *only* -- and they were internal approval
    # requests ("Approve action: github_list_issues") and engineering chores whose
    # descriptions merely mention a customer. `customer_word` is a substring test
    # over the whole description, so it cannot tell "a customer's repair" from "a
    # task about something a customer touched". The consequence was that the
    # stale-task reaper exempted 160 of 164 and closed nothing, while the
    # active-task ceiling sat full at 300/300 and the company could not file a
    # work order, a finding or an approval at all.
    #
    # This is deliberately the narrowest exemption that unjams it: the `approval`
    # tag is written only by `_create_approval_task` and `_enforce_action_policy`,
    # never by customer intake, so no real customer job can carry it. Every other
    # marker -- lpt_tag, repair_title, customer_word on non-approval rows,
    # hub_case_path -- protects exactly what it protected before, including the
    # D2907 owner/money cases.
    if "approval" in lowered:
        return []
    if LPT_TAG in lowered:
        markers.append("lpt_tag")

    title = str(_row_get(row, "title", "") or "")
    description = str(_row_get(row, "description", "") or "")

    if _TITLE_INTAKE_RE.match(title) or _TITLE_INTAKE_RE.match(description):
        markers.append("repair_title")

    if _CUSTOMER_WORD_RE.search(title) or _CUSTOMER_WORD_RE.search(description):
        markers.append("customer_word")

    raw_metadata = str(_row_get(row, "metadata_json", "") or "")
    if _HUB_CASE_PATH in raw_metadata:
        markers.append("hub_case_path")

    return markers


def looks_like_customer_work(row: Any) -> bool:
    """True when `row` carries at least one LPT customer marker."""
    return bool(customer_markers(row))


def is_stall_flag(row: Any) -> bool:
    """True when `row` is a flag THIS module created about a customer job."""
    tags = _decode_json(_row_get(row, "tags_json", "[]"), [])
    if not isinstance(tags, (list, tuple)):
        return False
    return STALL_FLAG_TAG in {str(tag).strip().lower() for tag in tags}


# ── Counting a phone number is NOT a customer marker ──────────────────
# Kept as a named helper so the evaluation above is reproducible rather than
# folklore: `_looks_like_phone` is what a future reader would reach for, and
# this comment is the reason they should not.
def _looks_like_phone(text: str) -> bool:
    return bool(_PHONE_RE.search(text or ""))


# ── Config ────────────────────────────────────────────────────────────
def _env_int(name: str, default: int) -> int:
    """Positive int from the environment, falling back loudly, never fatally."""
    raw = os.environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    try:
        value = int(str(raw).strip())
    except (TypeError, ValueError):
        log.warning("%s=%r is not an integer; using %d", name, raw, default)
        return default
    if value <= 0:
        log.warning("%s=%r is not positive; using %d", name, raw, default)
        return default
    return value


def watch_enabled() -> bool:
    raw = str(os.environ.get(ENV_ENABLED, "1")).strip().lower()
    return raw not in {"0", "false", "no", "off", "disabled"}


def _parse_utc(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# ── Storage ───────────────────────────────────────────────────────────
_CREATE_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {STALL_TABLE} (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL,
    stall_anchor TEXT NOT NULL,
    days_stalled INTEGER NOT NULL DEFAULT 0,
    tier TEXT NOT NULL DEFAULT 'silent',
    marker TEXT NOT NULL DEFAULT '',
    status_at_detection TEXT NOT NULL DEFAULT '',
    first_detected_at TEXT NOT NULL,
    last_detected_at TEXT NOT NULL,
    last_alerted_at TEXT,
    alert_count INTEGER NOT NULL DEFAULT 0,
    alert_task_id INTEGER,
    closed_at TEXT
)
"""

_CREATE_INDEX_SQL = (
    f"CREATE UNIQUE INDEX IF NOT EXISTS ux_customer_stall_episode "
    f"ON {STALL_TABLE}(task_id, stall_anchor)"
)


def _ensure_stall_table(conn, db_url: str) -> None:
    """Create the episode table if absent. Additive and idempotent; drops nothing.

    Deliberately NOT memoised per db_url: the repo's own convention
    (``_AGENT_QUESTION_COLUMNS_ENSURED``) memoises by URL, which breaks the
    moment two tests share the string ``":memory:"`` or the file is replaced
    under a live URL. ``IF NOT EXISTS`` is a cheap schema lookup, so it is run
    every time instead.
    """
    from app.database import _db_lock

    with _db_lock:
        conn.execute(_CREATE_TABLE_SQL)
        conn.execute(_CREATE_INDEX_SQL)
        conn.commit()


# ── Escalation (flag only, never send) ────────────────────────────────
def _escalation_body(task_id: int, title: str, status: str, days: int, tier: str,
                     markers: list[str], progress_pct: Any, alert_task_id: int | None) -> str:
    """The text of the flag. Deliberately free of task description content."""
    lines = [
        f"Task #{task_id} is customer-facing work that has not moved in "
        f"{days} days.",
        "",
        f"- status: {status}",
        f"- progress: {progress_pct if progress_pct is not None else 0}%",
        f"- last update: {days} days ago (tasks.updated_at unchanged since)",
        f"- customer marker(s): {', '.join(markers)}",
        f"- waiting tier: {tier}",
    ]
    if alert_task_id:
        lines.append(f"- tracker flag: task #{alert_task_id}")
    lines += [
        "",
        "This is a flag, not a customer message. Nothing has been sent to the "
        "customer or to the owner. The job's own description holds the "
        "customer contact route and the current next step; the tracker flag "
        "carries only this pointer, on purpose.",
    ]
    return "\n".join(lines)


def _escalate(
    conn,
    db_url: str,
    *,
    task_id: int,
    title: str,
    status: str,
    days: int,
    tier: str,
    markers: list[str],
    progress_pct: Any,
    stall_anchor: str,
    re_alert: bool,
) -> int | None:
    """Write the flag to every surface a human reads. Returns the flag task id.

    Surfaces, in the order they are written:

    1. a task in the tracker (the thing someone actually opens)
    2. a ``vp_inbox`` row at priority ``p1`` -- the queue is 1,925 ``p3``
       ``fyi`` rows, so ``p1`` is what makes this sort above the noise
    3. an ``activity_log`` line, plus the P2 escalation router entry, which is
       how the lifecycle sweep reports everything else
    4. ``metadata_json.customer_stall`` on the stalled task itself, for any
       owner-facing digest that reads task metadata

    No customer or owner contact of any kind happens here.
    """
    from app.database import create_task, log_activity, vp_inbox_add

    alert_task_id: int | None = None
    dedupe_key = f"customer-stall:{task_id}:{stall_anchor}"
    body = _escalation_body(
        task_id, title, status, days, tier, markers, progress_pct, None
    )

    try:
        created = create_task(
            db_url,
            title=f"CUSTOMER STALL: #{task_id} {title[:110]}",
            description=body,
            priority="high",
            tags=[STALL_FLAG_TAG, LPT_TAG],
            # agent_id stays 'orchestrator' and assigned_to stays None ON
            # PURPOSE. lifecycle_sweep._ensure_priority_task_goal_coverage
            # skips a task whose target agent is 'orchestrator', so this flag
            # does not spawn an LLM goal that would spend budget (and risk an
            # outbound attempt) on a physical repair only a human can finish.
            agent_id="orchestrator",
            assigned_to=None,
            metadata={
                "customer_stall": {
                    "task_id": task_id,
                    "days_stalled": days,
                    "tier": tier,
                    "marker": ",".join(markers),
                    "stall_anchor": stall_anchor,
                    "flagged_by": STALL_SOURCE,
                }
            },
            # dedup_threshold=0: the fuzzy matcher (80% title overlap) would
            # merge two DIFFERENT customer jobs whose titles collide. This
            # table is full of such collisions ("Apple MacBook Air A1932 —
            # Yechezkel Yanofsky" appears dozens of times), and merging them
            # would under-alert. The dedupe_key below is exact, and the unique
            # index in customer_stall_alerts is the real guard.
            dedup_threshold=0,
            dedupe_key=dedupe_key,
        )
        if created and created > 0:
            alert_task_id = int(created)
    except Exception as exc:  # noqa: BLE001 - a flag that fails must not kill the sweep
        log.warning("Customer stall: tracker flag failed for task #%s: %s", task_id, exc)

    try:
        vp_inbox_add(
            db_url,
            source=STALL_SOURCE,
            kind="customer_stall",
            title=(
                f"Customer stall: #{task_id} untouched for {days} days "
                f"({status})"
            ),
            body=_escalation_body(
                task_id, title, status, days, tier, markers, progress_pct, alert_task_id
            ),
            priority="p1",
            ref_type="task",
            ref_id=str(task_id),
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Customer stall: VP inbox flag failed for #%s: %s", task_id, exc)

    try:
        log_activity(
            db_url,
            action="customer_stall_detected",
            detail=(
                f"Customer repair #{task_id} untracked for {days} days "
                f"({status}, tier={tier}, re_alert={re_alert})"
            ),
            agent_id=STALL_SOURCE,
            details={
                "task_id": task_id,
                "days_stalled": days,
                "tier": tier,
                "markers": markers,
                "status": status,
                "progress_pct": progress_pct,
                "stall_anchor": stall_anchor,
                "re_alert": re_alert,
                "alert_task_id": alert_task_id,
            },
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Customer stall: activity log failed for #%s: %s", task_id, exc)

    try:
        from app.services.escalation_router import (
            route_escalation,
            severity_for_class,
        )

        # P2 (functional), exactly as the lifecycle sweep reports stuck goals:
        # it logs an escalation_p2 activity row and returns 'escalate_ceo'. It
        # is NOT P1/P0, which are the only tiers that reach _notify_owner.
        #
        # `goal_id` carries a namespaced JOB KEY rather than a goal. The router's
        # only per-thing dedup key is (agent_id, goal_id) -- measured: with
        # goal_id=None it suppressed two of these three real jobs in one run,
        # because three stalled jobs looked like one repeated escalation. There
        # is no goal here on purpose (a goal would hand a physical repair to the
        # LLM work loop and spend budget), so the job identity rides the field
        # the router actually dedups on. `customer-stall:3132` can never collide
        # with a real goal id, and the only reader of escalation_p2 rows,
        # lifecycle_sweep._detect_stuck_goals, matches on real goal ids.
        route_escalation(
            severity=severity_for_class("functional"),
            agent_id=STALL_SOURCE,
            error_text=(
                f"Customer repair stalled: task #{task_id} "
                f"untouched {days}d ({tier}) — {title[:80]}"
            ),
            goal_id=f"customer-stall:{task_id}",
            db_url=db_url,
        )
    except Exception as exc:  # noqa: BLE001
        log.warning("Customer stall: escalation routing failed for #%s: %s", task_id, exc)

    try:
        _stamp_task_metadata(conn, db_url, task_id, days, tier, markers,
                             stall_anchor, alert_task_id)
    except Exception as exc:  # noqa: BLE001
        log.warning("Customer stall: metadata stamp failed for #%s: %s", task_id, exc)

    log.warning(
        "CUSTOMER STALL: task #%s (%s) untouched %dd, progress %s%%, "
        "markers=%s, tier=%s, flag_task=%s",
        task_id,
        status,
        days,
        progress_pct if progress_pct is not None else 0,
        ",".join(markers),
        tier,
        alert_task_id,
    )
    return alert_task_id


def _stamp_task_metadata(
    conn,
    db_url: str,
    task_id: int,
    days: int,
    tier: str,
    markers: list[str],
    stall_anchor: str,
    alert_task_id: int | None,
) -> None:
    """Write ``metadata_json.customer_stall`` WITHOUT touching ``updated_at``.

    This is the field an owner-facing digest can read:

        json_extract(metadata_json, '$.customer_stall.days_stalled')

    The direct UPDATE is deliberate. ``app.database.update_task`` stamps
    ``updated_at``, and this module's entire clock is ``updated_at`` -- using it
    here would make the stalled job look freshly handled and silently un-stall
    it. That is precisely the bug in ``staleness_detector._flag_stale_tasks``
    (see the module docstring), and it is pinned by a test.
    """
    from app.database import _db_lock

    row = conn.execute(
        "SELECT metadata_json FROM tasks WHERE id = ?", (task_id,)
    ).fetchone()
    if row is None:
        return
    metadata = _decode_json(_row_get(row, "metadata_json", "{}"), {})
    if not isinstance(metadata, dict):
        metadata = {}
    metadata["customer_stall"] = {
        "task_id": task_id,
        "days_stalled": days,
        "tier": tier,
        "marker": ",".join(markers),
        "stall_anchor": stall_anchor,
        "flagged_by": STALL_SOURCE,
        "alert_task_id": alert_task_id,
        "last_seen_at": datetime.now(timezone.utc).isoformat(),
    }
    with _db_lock:
        conn.execute(
            "UPDATE tasks SET metadata_json = ? WHERE id = ?",
            (json.dumps(metadata), task_id),
        )
        conn.commit()


# ── The watch ─────────────────────────────────────────────────────────
def run_customer_stall_watch(
    db_url: str,
    *,
    now: datetime | None = None,
    silent_days: int | None = None,
    declared_wait_days: int | None = None,
    re_alert_days: int | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Flag customer repairs that stopped moving. Never sends anything.

    Returns a summary. ``stalls_detected`` counts NEW episodes escalated on
    this run and is 0 on every run after the first until a job moves and stalls
    again; ``stalls_open`` is the standing count of live stalls and is what a
    digest wants.
    """
    from app.database import TASK_PENDING_WORK_STATUSES, _db_lock, _get_conn

    summary: dict[str, Any] = {
        "watch_enabled": watch_enabled(),
        "scanned": 0,
        "customer_tasks": 0,
        "stalls_open": 0,
        "stalls_detected": 0,
        "stalls_realerted": 0,
        "stalls_suppressed": 0,
        "alerts_open": 0,
        "stalls": [],
    }
    if not summary["watch_enabled"]:
        log.info(
            "Customer stall watch disabled via %s=%r",
            ENV_ENABLED,
            os.environ.get(ENV_ENABLED),
        )
        return summary

    silent = silent_days or _env_int(ENV_SILENT_DAYS, STALL_DAYS_SILENT_DEFAULT)
    declared = declared_wait_days or _env_int(
        ENV_DECLARED_WAIT_DAYS, STALL_DAYS_DECLARED_WAIT_DEFAULT
    )
    re_alert = re_alert_days or _env_int(ENV_RE_ALERT_DAYS, RE_ALERT_DAYS_DEFAULT)
    now = now or datetime.now(timezone.utc)

    conn = _get_conn(db_url)
    if not dry_run:
        _ensure_stall_table(conn, db_url)

    statuses = list(TASK_PENDING_WORK_STATUSES or ())
    if not statuses:
        return summary
    placeholders = ",".join("?" for _ in statuses)
    # Every active task is fetched and the age is decided in Python. This is
    # bounded (policy_active_task_ceiling is 300) and it removes any chance of
    # the SQL cutoff and the Python cutoff disagreeing about a date format --
    # this table holds both "2026-06-01T18:48:09.969081+00:00" and
    # "2026-06-01T19:03:51" spellings.
    rows = conn.execute(
        f"""SELECT id, title, description, status, progress_pct,
                   tags_json, metadata_json, created_at, updated_at
              FROM tasks
             WHERE status IN ({placeholders})
             ORDER BY updated_at ASC
             LIMIT 2000""",
        tuple(statuses),
    ).fetchall()

    stale_cutoff = now - timedelta(days=min(silent, declared))
    stalls: list[dict[str, Any]] = []

    for row in rows:
        summary["scanned"] += 1
        markers = customer_markers(row)
        if not markers:
            continue
        summary["customer_tasks"] += 1

        # The clock is `updated_at`: the one field the tracker actually
        # maintains, and the field whose equality with `created_at` is the
        # proof that nothing ever touched the job. (#3132/#4467/#4485 all have
        # updated_at == created_at.) Measured on the live table, #2444 -- a real
        # customer data-recovery job -- has NO updated_at at all, so the fallback
        # to `created_at` is not defensive padding: without it the single most
        # forgotten customer job in the table would be the one row this watch
        # could not see.
        updated_at = _parse_utc(_row_get(row, "updated_at")) or _parse_utc(
            _row_get(row, "created_at")
        )
        if updated_at is None:
            continue
        if updated_at > stale_cutoff:
            continue

        task_id = int(_row_get(row, "id"))
        status = str(_row_get(row, "status", "") or "")
        title = str(_row_get(row, "title", "") or "")
        progress_pct = _row_get(row, "progress_pct")
        tier = "declared_wait" if status in DECLARED_WAIT_STATUSES else "silent"
        threshold = declared if tier == "declared_wait" else silent
        days = int((now - updated_at).total_seconds() // 86400)
        if days < threshold:
            continue

        stall_anchor = str(
            _row_get(row, "updated_at") or _row_get(row, "created_at") or ""
        )
        summary["stalls_open"] += 1
        stalls.append(
            {
                "task_id": task_id,
                "title": title[:160],
                "status": status,
                "days_stalled": days,
                "progress_pct": progress_pct,
                "tier": tier,
                "markers": markers,
                "stall_anchor": stall_anchor,
            }
        )

        if dry_run:
            continue

        now_iso = now.isoformat()
        with _db_lock:
            cur = conn.execute(
                f"""INSERT OR IGNORE INTO {STALL_TABLE}
                    (task_id, stall_anchor, days_stalled, tier, marker,
                     status_at_detection, first_detected_at, last_detected_at,
                     last_alerted_at, alert_count, alert_task_id)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL, 0, NULL)""",
                (
                    task_id,
                    stall_anchor,
                    days,
                    tier,
                    ",".join(markers),
                    status,
                    now_iso,
                    now_iso,
                ),
            )
            inserted = int(cur.rowcount or 0) == 1
            conn.commit()

        existing = conn.execute(
            f"""SELECT last_alerted_at, alert_count, alert_task_id
                  FROM {STALL_TABLE}
                 WHERE task_id = ? AND stall_anchor = ?""",
            (task_id, stall_anchor),
        ).fetchone()

        with _db_lock:
            conn.execute(
                f"""UPDATE {STALL_TABLE}
                       SET days_stalled = ?, last_detected_at = ?
                     WHERE task_id = ? AND stall_anchor = ?""",
                (days, now_iso, task_id, stall_anchor),
            )
            conn.commit()

        last_alerted = _parse_utc(_row_get(existing, "last_alerted_at"))
        if not inserted and last_alerted is not None:
            if (now - last_alerted) < timedelta(days=re_alert):
                summary["stalls_suppressed"] += 1
                log.debug(
                    "Customer stall already flagged: task #%s (%dd, last alert %s)",
                    task_id,
                    days,
                    _row_get(existing, "last_alerted_at"),
                )
                continue
            re_alerting = True
        else:
            re_alerting = not inserted

        alert_task_id = _escalate(
            conn,
            db_url,
            task_id=task_id,
            title=title,
            status=status,
            days=days,
            tier=tier,
            markers=markers,
            progress_pct=progress_pct,
            stall_anchor=stall_anchor,
            re_alert=re_alerting,
        )

        with _db_lock:
            conn.execute(
                f"""UPDATE {STALL_TABLE}
                       SET last_alerted_at = ?, alert_count = alert_count + 1,
                           alert_task_id = COALESCE(?, alert_task_id)
                     WHERE task_id = ? AND stall_anchor = ?""",
                (now_iso, alert_task_id, task_id, stall_anchor),
            )
            conn.commit()

        if inserted:
            summary["stalls_detected"] += 1
        else:
            summary["stalls_realerted"] += 1
        stalls[-1]["alert_task_id"] = alert_task_id

    summary["stalls"] = stalls

    try:
        with _db_lock:
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM {STALL_TABLE} WHERE closed_at IS NULL"
            ).fetchone()
        summary["alerts_open"] = int(_row_get(row, "c", 0) or 0)
    except Exception as exc:  # noqa: BLE001 - no table yet means no alerts yet
        log.debug("Customer stall: open-alert count unavailable: %s", exc)
        summary["alerts_open"] = 0

    if summary["stalls_detected"] or summary["stalls_realerted"]:
        log.warning(
            "Customer stall watch: %d new stall(s), %d re-alert(s), "
            "%d suppressed, %d open, %d customer task(s) of %d active scanned",
            summary["stalls_detected"],
            summary["stalls_realerted"],
            summary["stalls_suppressed"],
            summary["stalls_open"],
            summary["customer_tasks"],
            summary["scanned"],
        )
    elif summary["stalls_open"]:
        log.info(
            "Customer stall watch: %d stall(s) open, all already flagged "
            "(no new alerts this run)",
            summary["stalls_open"],
        )
    else:
        log.info(
            "Customer stall watch: no stalled customer work "
            "(%d customer task(s) of %d active scanned)",
            summary["customer_tasks"],
            summary["scanned"],
        )
    return summary


def customer_stall_report(db_url: str, **kwargs: Any) -> dict[str, Any]:
    """Read-only view of live customer stalls, for an owner-facing digest.

    Runs the identical detection with writes disabled, then reports the alert
    episodes already on record. A digest should call this rather than the
    watch: reading a report must never create a flag.
    """
    report = run_customer_stall_watch(db_url, dry_run=True, **kwargs)
    report["alerts_open"] = 0
    try:
        from app.database import _get_conn

        conn = _get_conn(db_url)
        row = conn.execute(
            f"SELECT COUNT(*) AS c FROM {STALL_TABLE} WHERE closed_at IS NULL"
        ).fetchone()
        report["alerts_open"] = int(_row_get(row, "c", 0) or 0)
    except Exception:  # noqa: BLE001 - no table yet means no alerts yet
        pass
    return report
