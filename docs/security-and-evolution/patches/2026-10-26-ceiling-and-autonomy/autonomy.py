"""Graduated Autonomy Framework — Phase 7.

5-level trust system (L0-L4) with per-action-type assignment and
automatic promotion/demotion based on track record.

Levels:
  L0 (shadow)    — Log only, never execute. For legal/irreversible actions.
  L1 (suggest)   — Propose to owner, require explicit approval.
  L2 (approve)   — Execute after owner quick-approve (SMS/dashboard).
  L3 (act+undo)  — Execute with cancel window (undo via delayed_executor).
  L4 (autonomous) — Execute immediately, no human in loop.

The autonomy level matrix is defined per action type. Levels can be
promoted (after N consecutive successes) or demoted (on error spike).

Fail-closed default
-------------------
A name the matrix does not classify resolves to ``UNCLASSIFIED_ACTION_LEVEL``
(L1, suggest) — never to L4.  The old behaviour here was
``return AutonomyLevel.L4_AUTONOMOUS  # bias towards action``, so every action
the dispatcher gained before somebody classified it ran with no human in the
loop.  Two further rules make that default hold against the *other* level
sources:

* ``max`` on a matrix row is a hard ceiling, not a description.  ``get_level()``
  clamps the in-memory override, the ``autonomy_levels`` DB row and the matrix
  default to it, so auto-promotion, a manual override, or an override written by
  another module (``lifecycle_sweep`` promotes expired approvals) cannot lift a
  restricted action above its policy level.
* a ``autonomy_levels`` row for a name with no matrix row is not a
  classification: the DB is not consulted for such a name and the fail-closed
  default answers instead.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import IntEnum
from threading import Lock
from typing import Any

log = logging.getLogger(__name__)

_autonomy_lock = Lock()


# ---------------------------------------------------------------------------
# Level definitions
# ---------------------------------------------------------------------------


class AutonomyLevel(IntEnum):
    """Trust levels from most restricted to fully autonomous."""

    L0_SHADOW = 0  # Log only, never execute
    L1_SUGGEST = 1  # Propose, require explicit approval
    L2_APPROVE = 2  # Execute after quick-approve
    L3_ACT_UNDO = 3  # Execute with cancel window
    L4_AUTONOMOUS = 4  # Execute immediately


@dataclass(frozen=True)
class ActionAutonomy:
    """Autonomy assignment for a specific action type."""

    action: str
    current_level: AutonomyLevel
    max_safe_level: AutonomyLevel
    category: str = "general"
    notes: str = ""


# ---------------------------------------------------------------------------
# Hand-written autonomy policy (from 004-synthesis.md)
# ---------------------------------------------------------------------------

# Max safe level per action type — the ceiling that auto-promotion
# can never exceed (even with perfect track record).
#
# This is the HAND-WRITTEN half of the policy: the actions a human reviewed.
# It is deliberately not the whole story — see GENERATED_MATRIX below, which
# classifies every action the dispatcher can route, and the merge where the two
# are combined.  A row that disagrees with the generated policy fails
# generation (app/services/autonomy_matrix_generator.py).

CURATED_MATRIX: dict[str, dict[str, Any]] = {
    # Read-only / internal — fully autonomous, immune to demotion
    "list_tasks": {"max": 4, "default": 4, "cat": "tasks", "no_demote": True},
    "memory_search": {"max": 4, "default": 4, "cat": "memory", "no_demote": True},
    "memory_save": {"max": 4, "default": 4, "cat": "memory", "no_demote": True},
    "save_memory": {"max": 4, "default": 4, "cat": "memory", "no_demote": True},
    "memory_sync": {"max": 4, "default": 4, "cat": "memory", "no_demote": True},
    "system_health": {"max": 4, "default": 4, "cat": "system", "no_demote": True},
    "calendar_list": {"max": 4, "default": 4, "cat": "calendar"},
    "gmail_list": {"max": 4, "default": 4, "cat": "email"},
    "gmail_read": {"max": 4, "default": 4, "cat": "email"},
    "gmail_search": {"max": 4, "default": 4, "cat": "email", "no_demote": True},
    "ha_status": {"max": 4, "default": 4, "cat": "home"},
    "ha_states": {"max": 4, "default": 4, "cat": "home", "no_demote": True},
    "web_search": {"max": 4, "default": 4, "cat": "research"},
    "fetch_url": {"max": 4, "default": 4, "cat": "research", "no_demote": True},
    "qb_snapshot": {"max": 4, "default": 4, "cat": "finance"},
    "qb_search": {"max": 4, "default": 4, "cat": "finance", "no_demote": True},
    "managed_workflow_status": {"max": 4, "default": 4, "cat": "system", "no_demote": True},
    "ledger_source_registry": {"max": 4, "default": 4, "cat": "finance", "no_demote": True},
    # Reversible / low risk — autonomous OK; task management is immune to demotion
    # because failures indicate system bugs, not unsafe actions.
    "create_task": {"max": 4, "default": 4, "cat": "tasks", "no_demote": True},
    "update_task": {"max": 4, "default": 4, "cat": "tasks", "no_demote": True},
    "close_task": {"max": 4, "default": 4, "cat": "tasks", "no_demote": True},
    "complete_goal_step": {
        "max": 4,
        "default": 4,
        "cat": "tasks",
        "no_demote": True,
        "notes": "Internal workflow bookkeeping should execute autonomously.",
    },
    "delegate_task": {
        "max": 4,
        "default": 4,
        "cat": "tasks",
        "no_demote": True,
        "notes": "Internal cross-department delegation is safe to execute.",
    },
    "schedule_reminder": {"max": 4, "default": 4, "cat": "tasks"},
    "cancel_reminder": {"max": 4, "default": 4, "cat": "tasks"},
    "calendar_create": {"max": 4, "default": 4, "cat": "calendar"},
    "calendar_update": {"max": 4, "default": 4, "cat": "calendar"},
    # Outbound communication — act with cancel window
    "send_sms": {
        "max": 3,
        "default": 3,
        "cat": "comms",
        "notes": (
            "SMS to the owner always autonomous. Twilio SMS is owner-only by "
            "contract (settings.twilio_sms_owner_only; _exec_send_sms refuses a "
            "non-owner recipient and points the caller at dialpad_send_sms), so "
            "this is the notification channel the company uses to ask the owner "
            "— restricting it would mean a suggestion could never be delivered. "
            "Third-party SMS is dialpad_send_sms/gv_send_sms, which are L1."
        ),
    },
    "dialpad_send_sms": {
        "max": 1,
        "default": 1,
        "cat": "comms",
        "notes": (
            "RESTRICTED (changed from L3 by the evolve3 gate workstream): this "
            "sends SMS to a customer from the live business line. Outbound to a "
            "human is irreversible, so it queues for explicit owner approval. "
            "The previous L3 was a blanket 'routine operational SMS' judgement "
            "made before the outbound consequence was written down."
        ),
    },
    "gmail_send": {
        "max": 1,
        "default": 1,
        "cat": "email",
        "notes": (
            "RESTRICTED (changed from L3 by the evolve3 gate workstream): "
            "outbound email to a third party is irreversible once delivered. "
            "Queues for explicit owner approval."
        ),
    },
    "gmail_draft": {"max": 4, "default": 4, "cat": "email", "notes": "Drafts are safe"},
    # Home automation — careful
    "ha_call_service": {"max": 3, "default": 3, "cat": "home"},
    "ha_doors": {
        "max": 3,
        "default": 3,
        "cat": "home",
        "notes": "Door unlock is fine — act+undo window for safety",
    },
    "ha_climate": {"max": 3, "default": 3, "cat": "home"},
    # Financial — conservative
    "propose_spend_request": {
        "max": 3,
        "default": 3,
        "cat": "finance",
        "notes": "Routine spending under $50 can be executed. Larger amounts or new vendor relationships need owner approval.",
    },
    "qb_query": {"max": 4, "default": 4, "cat": "finance", "notes": "Read-only"},
    "qb_reconciliation": {"max": 3, "default": 3, "cat": "finance"},
    "alibaba_onetalk_automation": {
        "max": 3,
        "default": 3,
        "cat": "procurement",
        "notes": (
            "Routine supplier dashboard/report/follow-up automation is allowed; "
            "the tool must not place final orders or make payments."
        ),
    },
    # GitHub — moderate
    "github_read_file": {"max": 4, "default": 4, "cat": "code"},
    "github_list_dir": {"max": 4, "default": 4, "cat": "code"},
    "github_list_issues": {"max": 4, "default": 4, "cat": "code"},
    "github_list_prs": {"max": 4, "default": 4, "cat": "code"},
    "github_write_file": {"max": 3, "default": 3, "cat": "code"},
    "github_create_issue": {"max": 4, "default": 4, "cat": "code"},
    "github_create_pr": {"max": 3, "default": 3, "cat": "code"},
    # Repo actions — read-only operations are fully autonomous
    "repo_list_dir": {"max": 4, "default": 4, "cat": "code"},
    "repo_read_file": {"max": 4, "default": 4, "cat": "code"},
    "repo_search": {"max": 4, "default": 4, "cat": "code"},
    "repo_run_command": {"max": 3, "default": 3, "cat": "code"},
    # Browser automation — careful
    "browser_goto": {"max": 3, "default": 3, "cat": "browser"},
    "browser_click": {"max": 3, "default": 3, "cat": "browser"},
    "browser_fill": {"max": 3, "default": 3, "cat": "browser"},
    "browser_act": {"max": 3, "default": 3, "cat": "browser"},
    # Self-modification — restricted
    "code_edit": {
        "max": 3,
        "default": 3,
        "cat": "system",
        "notes": "Self-improvement is encouraged. Avoid editing protected infrastructure files.",
    },
    "build_tool": {"max": 4, "default": 3, "cat": "system"},
    # Permanently restricted — L0 or L1
    "propose_human_job": {
        "max": 1,
        "default": 1,
        "cat": "legal",
        "notes": "Legal commitments need human",
    },
}


# ---------------------------------------------------------------------------
# Generated per-action policy — one explicit, justified row for every action
# ---------------------------------------------------------------------------
#
# CURATED_MATRIX above only classifies the actions somebody remembered to write
# down.  The action dispatcher in app/chat_action_runtime.py knows far more names
# than this dict does, and a name missing here used to fall through to
# get_level()'s unknown-action branch — which was L4 (autonomous).
#
# GENERATED_MATRIX supplies one explicit row for every name in that dispatcher
# chain (enumerated from the real source file by AST, not a hardcoded list) plus
# every name that exists in autonomy_levels.  Each row carries:
#
#   default  — the level get_level() returns on the matrix path (the path the
#              live gate agent_worker._check_autonomy uses)
#   max      — the hard ceiling
#   policy   — 'restricted' | 'act_undo' | 'curated' | 'autonomous'
#   reason   — why that level, one line
#
# The classification was made by consequence, not by blanket: irreversible /
# money / outbound / people / production-destructive names are L0 or L1, and
# read-only, internal or otherwise reversible names keep the autonomy they had.
# See app/services/autonomy_matrix_generator.py for the buckets and their
# written-out criteria.
#
# Merge order: GENERATED_MATRIX wins for every name it covers.  That is
# deliberate — the safety policy must not be silently overridden by a
# hand-written row, and the generator refuses to emit a table whose restricted
# set disagrees with a curated row.  CURATED_MATRIX still supplies the rows for
# actions that are neither dispatched nor in autonomy_levels.
#
# DEFAULT_MATRIX stays the public name for the merged view — other modules and
# tests read it.

from app.services.autonomy_matrix_generated import (  # noqa: E402
    AUTONOMOUS_ACTIONS,
    GENERATED_MATRIX,
    POLICY_REASONS,
    RESTRICTED_ACTION_LEVELS,
)

DEFAULT_MATRIX: dict[str, dict[str, Any]] = {**CURATED_MATRIX, **GENERATED_MATRIX}

__all__ = [
    "ActionAutonomy",
    "AutonomyLevel",
    "AUTONOMOUS_ACTIONS",
    "CURATED_MATRIX",
    "DEFAULT_MATRIX",
    "GENERATED_MATRIX",
    "POLICY_REASONS",
    "RESTRICTED_ACTION_LEVELS",
    "UNCLASSIFIED_ACTION_LEVEL",
    "get_autonomy_matrix",
    "get_autonomy_stats",
    "get_level",
    "record_failure",
    "record_success",
    "set_level_override",
    "should_execute",
]

# What an action nobody has classified resolves to.
#
# This used to be L4 (autonomous) — "bias towards action" — so any action the
# dispatcher gained before somebody classified it executed immediately, with no
# human in the loop.  An autonomous system whose default is maximum autonomy is
# not a safety system: the default must be the *safest* action, and it is
# L1 (suggest) — propose it to the owner and require explicit approval.
UNCLASSIFIED_ACTION_LEVEL: AutonomyLevel = AutonomyLevel.L1_SUGGEST


# ---------------------------------------------------------------------------
# Autonomy state tracking (in-memory + DB persistence)
# ---------------------------------------------------------------------------

# Track consecutive successes/failures per action type
_track: dict[str, dict[str, int]] = {}

# Override levels (from DB or manual config)
#
# Clamped to the matrix ceiling on the way out of get_level(): an override is a
# request, and the policy ceiling decides.  ``lifecycle_sweep`` writes L4 into
# this dict for actions whose approval expired; for a restricted action that
# write is now inert (get_level clamps it back to the row's ``max``).
_level_overrides: dict[str, int] = {}

# Promotion thresholds
PROMOTE_AFTER_SUCCESSES = 8  # Promote after N consecutive successes
DEMOTE_AFTER_FAILURES = 5  # Demote after N failures in window
FAILURE_WINDOW_SECONDS = 3600  # 1 hour window for failure counting
_failure_times: dict[str, list[float]] = {}

# Auto-recovery cooldown: if an action stays demoted below its default
# for this long (seconds) without new failures, restore to default.
COOLDOWN_RESTORE_SECONDS = 2 * 3600  # 2 hours
_last_demoted_at: dict[str, float] = {}  # action -> time.time()

# DB table flag
_table_created = False

# One-time cleanup flag — clear stale demotions for newly-added matrix entries
_stale_overrides_cleaned = False


def _get_autonomy_conn(db_url: str) -> sqlite3.Connection:
    from app.database import _get_conn

    return _get_conn(db_url)


def _cleanup_stale_overrides() -> None:
    """Remove in-memory overrides AND DB rows for actions that are now in
    CURATED_MATRIX but were previously demoted when they were 'unknown'
    (max defaulted to 2).  This lets them start fresh at their correct
    default level.

    Scope note (fail-closed gate workstream): this walks CURATED_MATRIX, not the
    merged DEFAULT_MATRIX.  The merged view contains a generated row for every
    dispatched action, and this routine treats ``default`` as a floor and WRITES
    it into autonomy_levels.  Iterating the merged view would replay a policy
    default into the live database on startup — including raising the level of a
    DB row that was deliberately lower.  Walking the curated matrix keeps this
    cleanup exactly as narrow as it was before the generated table existed.
    """
    global _stale_overrides_cleaned
    if _stale_overrides_cleaned:
        return
    _stale_overrides_cleaned = True

    reset_actions: list[str] = []
    for action_name, entry in CURATED_MATRIX.items():
        default = entry.get("default", 3)
        # In-memory overrides
        if action_name in _level_overrides:
            override = _level_overrides[action_name]
            if override < default:
                log.info(
                    "Autonomy: clearing stale override for %s (was L%d, default L%d)",
                    action_name,
                    override,
                    default,
                )
                del _level_overrides[action_name]
                reset_actions.append(action_name)
        else:
            # Track for DB check even if no in-memory override
            reset_actions.append(action_name)

    # Also reset DB rows where current_level < new default
    if reset_actions:
        try:
            from app.config import settings as _cfg

            db_url = getattr(_cfg, "database_url", "") or ""
            if db_url:
                conn = _get_autonomy_conn(db_url)
                _ensure_table(conn)
                for action_name in reset_actions:
                    entry = CURATED_MATRIX[action_name]
                    default = entry.get("default", 3)
                    cur = conn.execute(
                        "SELECT current_level FROM autonomy_levels WHERE action_name=?",
                        (action_name,),
                    ).fetchone()
                    if cur and cur[0] < default:
                        log.info(
                            "Autonomy: resetting DB level for %s from L%d to L%d",
                            action_name,
                            cur[0],
                            default,
                        )
                        conn.execute(
                            "UPDATE autonomy_levels SET current_level=?, max_level=?, updated_at=strftime('%Y-%m-%dT%H:%M:%S', 'now') WHERE action_name=?",
                            (default, entry.get("max", 4), action_name),
                        )
                conn.commit()
        except Exception as exc:
            log.warning("Autonomy: DB stale override cleanup failed: %s", exc)


def _ensure_table(conn: sqlite3.Connection) -> None:
    global _table_created
    if _table_created:
        row = conn.execute("""
            SELECT 1
            FROM sqlite_master
            WHERE type = 'table' AND name = 'autonomy_levels'
            """).fetchone()
        if row:
            return
    conn.execute("""
        CREATE TABLE IF NOT EXISTS autonomy_levels (
            action_name TEXT PRIMARY KEY,
            current_level INTEGER NOT NULL,
            max_level INTEGER NOT NULL,
            successes INTEGER NOT NULL DEFAULT 0,
            failures INTEGER NOT NULL DEFAULT 0,
            last_promoted_at TEXT,
            last_demoted_at TEXT,
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
    """)
    conn.commit()
    _table_created = True


# ---------------------------------------------------------------------------
# Core API
# ---------------------------------------------------------------------------


def ceiling_for(action_name: str) -> int:
    """The hard ceiling for an action.

    ``max`` on a matrix row is documented as "the ceiling that auto-promotion
    can never exceed".  That was not true: ``_level_overrides`` was returned
    before the ceiling was ever consulted, and ``lifecycle_sweep`` wrote L4 into
    it.  This function is how every level source is made to respect the ceiling.

    A name the matrix does not classify gets the fail-closed default: a name
    nobody classified may not be promoted either.
    """
    entry = DEFAULT_MATRIX.get(action_name)
    if entry is None:
        return int(UNCLASSIFIED_ACTION_LEVEL)
    return int(entry.get("max", int(UNCLASSIFIED_ACTION_LEVEL)))


def _clamp_to_ceiling(action_name: str, level: int) -> AutonomyLevel:
    """Clamp a resolved level to the policy ceiling, logging when it binds."""
    bounded = max(0, min(int(level), 4))
    ceiling = ceiling_for(action_name)
    if bounded > ceiling:
        log.info(
            "Autonomy CLAMP: %s L%d -> L%d (policy ceiling for %s)",
            action_name,
            bounded,
            ceiling,
            DEFAULT_MATRIX.get(action_name, {}).get("policy", "unclassified"),
        )
        bounded = ceiling
    return AutonomyLevel(bounded)


def _level_age_seconds(value: Any) -> float | None:
    """Seconds since the autonomy row last moved, or None if unparseable.

    Two stored formats exist in `autonomy_levels`: the `_persist_level` writer
    stores `datetime.now(timezone.utc).isoformat()` (with a `+00:00` offset and
    microseconds) while older / imported rows carry SQLite's `datetime('now')`
    (`2026-06-04 18:11:29`, a space separator and no zone). Both are real; both
    must parse, or the cooldown silently never fires for half the table.
    """
    if not value:
        return None
    text = str(value).strip().replace("Z", "+00:00")
    try:
        from datetime import datetime, timezone

        parsed = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        from datetime import timezone

        parsed = parsed.replace(tzinfo=timezone.utc)
    return max(0.0, time.time() - parsed.timestamp())


def get_level(action_name: str, settings: Any = None) -> AutonomyLevel:
    """Get the current autonomy level for an action type."""
    # One-time cleanup of stale demotions from before matrix additions
    _cleanup_stale_overrides()

    # Check override first
    if action_name in _level_overrides:
        override = _level_overrides[action_name]
        # Cooldown recovery: if demoted below default for longer than
        # COOLDOWN_RESTORE_SECONDS with no new failures, auto-restore.
        entry = DEFAULT_MATRIX.get(action_name)
        if entry and override < entry.get("default", 3):
            demoted_ts = _last_demoted_at.get(action_name, 0.0)
            if demoted_ts and (time.time() - demoted_ts >= COOLDOWN_RESTORE_SECONDS):
                default_lvl = entry["default"]
                log.info(
                    "Autonomy COOLDOWN-RESTORE: %s L%d → L%d"
                    " (demoted %ds ago, threshold %ds)",
                    action_name,
                    override,
                    default_lvl,
                    int(time.time() - demoted_ts),
                    COOLDOWN_RESTORE_SECONDS,
                )
                _level_overrides[action_name] = default_lvl
                _last_demoted_at.pop(action_name, None)
                _track.pop(action_name, None)
                _failure_times.pop(action_name, None)
                max_lvl = entry.get("max", default_lvl)
                _persist_level(
                    action_name,
                    default_lvl,
                    max_lvl,
                    "promoted",
                    settings,
                )
                return _clamp_to_ceiling(action_name, default_lvl)
        return _clamp_to_ceiling(action_name, override)

    entry = DEFAULT_MATRIX.get(action_name)

    # Check DB — but only for a name the matrix classifies.  A lone
    # autonomy_levels row is not a classification: it is what some past decision
    # recorded, possibly when the old fail-open default was in force, and letting
    # it decide would reopen the hole through the DB.
    if entry is not None and settings:
        db_url = getattr(settings, "database_url", "") or ""
        if db_url:
            try:
                conn = _get_autonomy_conn(db_url)
                _ensure_table(conn)
                row = conn.execute(
                    "SELECT current_level, last_demoted_at, updated_at"
                    " FROM autonomy_levels WHERE action_name=?",
                    (action_name,),
                ).fetchone()
                if row:
                    stored = int(row[0])
                    default_lvl = int(entry.get("default", stored))
                    if stored < default_lvl:
                        # ── COOLDOWN RECOVERY, enforced on the DB row (2026-10-26) ──
                        # The same rule already exists for in-memory overrides 40
                        # lines above; it was never applied here, so a restart made
                        # every demotion permanent. Measured on the authority: 24 of
                        # 75 rows were stuck below their matrix default, months old,
                        # including `ask_owner` at L0_SHADOW -- a refused action can
                        # never succeed, and an action that never succeeds can never
                        # be re-promoted, so the lock was total (`get_current_datetime`
                        # L2, `gmail_accounts` L2, `contact_search` L2...).
                        #
                        # A demotion is a brake, not a sentence: after
                        # COOLDOWN_RESTORE_SECONDS without moving, the matrix default
                        # is the policy again. The anchor is the row's own last write
                        # (`last_demoted_at`, else `updated_at`), so a row with no
                        # demotion timestamp is judged by when it was last written
                        # rather than exempted forever. Nothing is raised above the
                        # matrix default and nothing above its ceiling.
                        age = _level_age_seconds(row[1] or row[2])
                        if age is not None and age >= COOLDOWN_RESTORE_SECONDS:
                            log.info(
                                "Autonomy COOLDOWN-RESTORE (db): %s L%d → L%d"
                                " (level last moved %.1fh ago, threshold %ds)",
                                action_name,
                                stored,
                                default_lvl,
                                age / 3600.0,
                                COOLDOWN_RESTORE_SECONDS,
                            )
                            try:
                                conn.execute(
                                    "UPDATE autonomy_levels SET current_level=?,"
                                    " max_level=?, last_demoted_at=NULL,"
                                    " updated_at=strftime('%Y-%m-%dT%H:%M:%S','now')"
                                    " WHERE action_name=?",
                                    (
                                        default_lvl,
                                        ceiling_for(action_name),
                                        action_name,
                                    ),
                                )
                                conn.commit()
                            except Exception:
                                pass
                            return _clamp_to_ceiling(action_name, default_lvl)
                    return _clamp_to_ceiling(action_name, stored)
            except Exception:
                pass

    # Fall back to the policy matrix — every action the dispatcher can route has
    # an explicit row here, generated from the dispatcher itself.
    if entry is not None:
        return AutonomyLevel(int(entry["default"]))

    # Nobody has classified this action: ask, do not act.
    #
    # This branch used to return L4_AUTONOMOUS ("bias towards action"), which
    # meant any action the dispatcher gained -- or any action invoked by name
    # that no matrix row mentioned -- executed immediately with no human in the
    # loop.  L1 (suggest) queues it for explicit owner approval instead.
    log.info(
        "Autonomy: %r is unclassified; resolving to %s (fail-closed default)",
        action_name,
        UNCLASSIFIED_ACTION_LEVEL.name,
    )
    return UNCLASSIFIED_ACTION_LEVEL


def should_execute(action_name: str, settings: Any = None) -> dict[str, Any]:
    """Determine whether an action should execute given its autonomy level.

    Returns dict with:
      - execute: bool — whether to proceed
      - level: int — current level
      - action: str — what to do ("execute", "execute_with_undo",
                      "request_approval", "suggest", "shadow_log")
    """
    level = get_level(action_name, settings)

    if level == AutonomyLevel.L0_SHADOW:
        return {
            "execute": False,
            "level": int(level),
            "level_name": "L0_SHADOW",
            "action": "shadow_log",
            "reason": "Action is in shadow mode (log only)",
        }
    elif level == AutonomyLevel.L1_SUGGEST:
        return {
            "execute": False,
            "level": int(level),
            "level_name": "L1_SUGGEST",
            "action": "suggest",
            "reason": "Action requires explicit owner approval",
        }
    elif level == AutonomyLevel.L2_APPROVE:
        return {
            "execute": False,
            "level": int(level),
            "level_name": "L2_APPROVE",
            "action": "request_approval",
            "reason": "Action requires quick-approve",
        }
    elif level == AutonomyLevel.L3_ACT_UNDO:
        return {
            "execute": True,
            "level": int(level),
            "level_name": "L3_ACT_UNDO",
            "action": "execute_with_undo",
            "reason": "Execute with cancel window",
        }
    else:  # L4
        return {
            "execute": True,
            "level": int(level),
            "level_name": "L4_AUTONOMOUS",
            "action": "execute",
            "reason": "Fully autonomous",
        }


# ---------------------------------------------------------------------------
# Track record and auto-promotion / auto-demotion
# ---------------------------------------------------------------------------


def record_success(action_name: str, settings: Any = None) -> None:
    """Record a successful action execution."""
    with _autonomy_lock:
        if action_name not in _track:
            _track[action_name] = {"successes": 0, "failures": 0}
        _track[action_name]["successes"] += 1
        _track[action_name]["failures"] = 0  # Reset failure streak

        # Check for auto-promotion
        if _track[action_name]["successes"] >= PROMOTE_AFTER_SUCCESSES:
            _try_promote(action_name, settings)
            _track[action_name]["successes"] = 0


def record_failure(action_name: str, settings: Any = None) -> None:
    """Record a failed action execution."""
    now = time.time()
    with _autonomy_lock:
        if action_name not in _track:
            _track[action_name] = {"successes": 0, "failures": 0}
        _track[action_name]["failures"] += 1
        _track[action_name]["successes"] = 0  # Reset success streak

        # Track failure times for window-based demotion
        if action_name not in _failure_times:
            _failure_times[action_name] = []
        _failure_times[action_name].append(now)

        # Clean old failures outside window
        cutoff = now - FAILURE_WINDOW_SECONDS
        _failure_times[action_name] = [
            t for t in _failure_times[action_name] if t >= cutoff
        ]

        # Check for auto-demotion
        if len(_failure_times[action_name]) >= DEMOTE_AFTER_FAILURES:
            _try_demote(action_name, settings)
            _failure_times[action_name] = []


def _try_promote(action_name: str, settings: Any = None) -> None:
    """Attempt to promote an action's autonomy level."""
    current = get_level(action_name, settings)
    max_level = ceiling_for(action_name)

    if int(current) >= max_level:
        return  # Already at max

    new_level = int(current) + 1
    _level_overrides[action_name] = new_level
    _persist_level(action_name, new_level, max_level, "promoted", settings)
    log.info(
        "Autonomy PROMOTED: %s L%d → L%d (after %d successes)",
        action_name,
        int(current),
        new_level,
        PROMOTE_AFTER_SUCCESSES,
    )


def _try_demote(action_name: str, settings: Any = None) -> None:
    """Demote an action's autonomy level after failures.

    Actions marked no_demote=True in DEFAULT_MATRIX are immune — their
    failures represent system bugs, not evidence the action is unsafe.
    """
    entry = DEFAULT_MATRIX.get(action_name, {})
    if entry.get("no_demote", False):
        log.debug(
            "Autonomy demotion skipped for %s (no_demote=True)",
            action_name,
        )
        return

    current = get_level(action_name, settings)

    if int(current) <= 0:
        return  # Already at minimum

    new_level = int(current) - 1
    max_level = ceiling_for(action_name)
    _level_overrides[action_name] = new_level
    _last_demoted_at[action_name] = time.time()
    _persist_level(action_name, new_level, max_level, "demoted", settings)
    log.warning(
        "Autonomy DEMOTED: %s L%d → L%d (after %d failures in %ds)",
        action_name,
        int(current),
        new_level,
        DEMOTE_AFTER_FAILURES,
        FAILURE_WINDOW_SECONDS,
    )


def _persist_level(
    action_name: str,
    level: int,
    max_level: int,
    event: str,
    settings: Any = None,
) -> None:
    """Persist level change to DB."""
    if not settings:
        return
    db_url = getattr(settings, "database_url", "") or ""
    if not db_url:
        return
    try:
        now = datetime.now(timezone.utc).isoformat()
        conn = _get_autonomy_conn(db_url)
        _ensure_table(conn)
        promoted_col = "last_promoted_at" if event == "promoted" else "last_demoted_at"
        conn.execute(
            f"""INSERT INTO autonomy_levels
                (action_name, current_level, max_level, updated_at, {promoted_col})
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(action_name) DO UPDATE SET
                    current_level=excluded.current_level,
                    updated_at=excluded.updated_at,
                    {promoted_col}=excluded.{promoted_col}""",
            (action_name, level, max_level, now, now),
        )
        conn.commit()
    except Exception as exc:
        log.error("Failed to persist autonomy level: %s", exc)


# ---------------------------------------------------------------------------
# Query / dashboard helpers
# ---------------------------------------------------------------------------


def get_autonomy_matrix(settings: Any = None) -> list[dict[str, Any]]:
    """Return the full autonomy matrix with current levels."""
    result = []
    for action, entry in sorted(DEFAULT_MATRIX.items()):
        current = get_level(action, settings)
        result.append(
            {
                "action": action,
                "current_level": int(current),
                "current_level_name": current.name,
                "max_safe_level": entry["max"],
                "default_level": entry["default"],
                "category": entry.get("cat", "general"),
                "policy": entry.get("policy", "curated"),
                "reason": entry.get("reason", ""),
                "notes": entry.get("notes", ""),
            }
        )
    return result


def get_autonomy_stats(settings: Any = None) -> dict[str, Any]:
    """Return aggregate autonomy statistics."""
    matrix = get_autonomy_matrix(settings)
    level_counts = {f"L{i}": 0 for i in range(5)}
    for item in matrix:
        key = f"L{item['current_level']}"
        level_counts[key] = level_counts.get(key, 0) + 1

    return {
        "total_actions": len(matrix),
        "level_distribution": level_counts,
        "track_record": {
            action: {
                "successes": data.get("successes", 0),
                "failures": data.get("failures", 0),
            }
            for action, data in _track.items()
        },
    }


def set_level_override(
    action_name: str,
    level: int,
    settings: Any = None,
) -> bool:
    """Manually override an action's autonomy level.

    Returns True if the override was accepted (within max bounds).
    """
    entry = DEFAULT_MATRIX.get(action_name)
    max_level = ceiling_for(action_name)
    if level < 0 or level > max_level:
        return False

    with _autonomy_lock:
        _level_overrides[action_name] = level
        _persist_level(action_name, level, max_level, "manual", settings)
    return True

