"""Chat action execution engine.

Parses structured action tags from LLM responses and executes them.
This gives the assistant real capabilities — sending SMS, creating tasks,
saving memories, doing web searches — all triggered from natural chat.

Action syntax in LLM output:
    [ACTION:send_sms|to=+1234567890|body=Hello there]
    [ACTION:create_task|title=Buy groceries|priority=high|due=2026-02-18]
    [ACTION:save_memory|content=User prefers morning updates|category=preferences]
    [ACTION:web_search|query=weather in lakewood nj]
"""

from __future__ import annotations

import hashlib
import json
import logging
import re as _re
import time
from typing import Any

from app.chat_action_code_edit import _exec_code_edit
from app.chat_action_notifications import (
    _create_approval_task,
    _sms_is_duplicate,
    format_agent_sms_body,
)
from app.chat_action_calendar import (
    _exec_calendar_create,
    _exec_calendar_delete,
    _exec_calendar_get,
    _exec_calendar_list,
    _exec_calendar_list_calendars,
    _exec_calendar_update,
)
from app.chat_action_agents import (
    _exec_delegate_task,
    _exec_fire_agent,
    _exec_hire_department,
    _exec_reactivate_agent,
    _exec_send_directive,
)
from app.chat_action_browser import (
    _exec_browser_act,
    _exec_browser_click,
    _exec_browser_fill,
    _exec_browser_goto,
    _exec_browser_run,
    _exec_browser_save_session,
    _exec_browser_screenshot,
    _exec_browser_sessions,
    _exec_browser_use_run,
    _exec_browser_session_list,
    _exec_browser_session_delete,
    _exec_browser_capture_session,
    _exec_cua_run,
    _exec_gv_read_conversation,
    _exec_gv_read_messages,
    _exec_gv_read_calls,
    _exec_gv_read_voicemails,
    _exec_gv_send_sms,
)
from app.chat_action_dynamic_tools import (
    _exec_build_tool,
    _exec_delete_tool,
    _exec_dynamic_tool,
    _exec_list_dynamic_tools,
    _exec_upgrade_tool,
)
from app.chat_action_gmail import (
    _exec_gmail_accounts,
    _exec_gmail_draft,
    _exec_gmail_list,
    _exec_gmail_read,
    _exec_gmail_search,
    _exec_gmail_send,
)
from app.chat_action_home_assistant import (
    _exec_ha_call_service,
    _exec_ha_climate,
    _exec_ha_doors,
    _exec_ha_entity,
    _exec_ha_security,
    _exec_ha_states,
    _exec_ha_status,
)
from app.chat_action_memory import (
    _exec_save_memory,
    _exec_memory_save,
    _exec_memory_search,
    _exec_memory_stats,
    _exec_memory_sync,
)
from app.chat_action_quickbooks import (
    _exec_ledger_source_registry,
    _exec_ledger_status,
    _exec_qb_accounts,
    _exec_qb_query,
    _exec_qb_reconciliation,
    _exec_qb_search,
    _exec_qb_snapshot,
    _exec_qb_status,
    _exec_qb_vendors,
)
from app.chat_action_repos import (
    _exec_github_create_issue,
    _exec_github_list_dir,
    _exec_github_list_issues,
    _exec_github_list_prs,
    _exec_github_read_file,
    _exec_repo_list_dir,
    _exec_repo_map,
    _exec_repo_read_file,
    _exec_repo_run_command,
    _exec_repo_search,
)
from app.chat_action_scheduling import (
    _exec_schedule_action,
    _exec_schedule_reminder,
)
from app.chat_action_system import (
    _exec_ask_advisor,
    _exec_deep_research,
    _exec_fetch_url,
    _exec_get_current_datetime,
    _exec_read_local_repo_file,
    _exec_system_health,
    _exec_web_search,
)
from app.chat_action_linux_pc import (
    _exec_linux_pc_ssh,
    _exec_linux_pc_status,
    _exec_linux_pc_list_usb,
    _exec_linux_pc_mount,
    _exec_linux_pc_unmount,
)
from app.chat_action_tasks import (
    _exec_create_task,
    _exec_complete_work,
    _exec_consolidate_tasks,
    _exec_enqueue_job,
    _exec_link_task_to_mission,
    _exec_list_tasks,
    _exec_start_work_session,
    _exec_task_hygiene,
    _exec_update_progress,
    _exec_update_task,
)
from app.chat_action_owner import (
    _exec_ask_owner,
    _exec_list_missions,
    _exec_propose_human_job,
    _exec_propose_mission,
    _exec_propose_owner_assumption,
    _exec_propose_spend_request,
    _exec_update_mission,
)
from app.chat_action_parsing import ActionResult, parse_actions
from app.chat_action_policy import (
    _enforce_action_policy,
    _normalize_params,
    _record_policy_success,
    _to_bool,
)
from app.chat_action_resilience import (
    _MAX_ACTION_RETRIES,
    _RETRY_BACKOFF,
    _CB_COOLDOWN,
    _CB_THRESHOLD,
    _cb_is_open,
    _cb_record_failure,
    _cb_record_success,
    _get_fix_hint,
    _should_record_circuit_breaker_failure,
    _should_retry_action_failure,
)
from app.chat_action_skills import _exec_import_skill, _exec_list_skills
from app.observability import langfuse_flush, langfuse_span, langfuse_update

__all__ = [
    "ActionResult",
    "parse_actions",
    "execute_actions",
    "format_action_results",
]

log = logging.getLogger(__name__)


def _exec_create_project(
    params: dict[str, str],
    *,
    settings: Any,
    agent_id: str,
) -> ActionResult:
    """Create a new project via the project hub."""
    from app.services.project_hub import create_project

    name = str(params.get("name") or "").strip()
    if not name:
        return ActionResult(
            action="create_project",
            success=False,
            detail="name is required",
        )

    project_type = str(params.get("project_type") or "general").strip() or "general"
    description = str(params.get("description") or "").strip()
    lead_agent = str(params.get("lead_agent") or "").strip() or None
    local_path = str(params.get("local_path") or "").strip() or None
    icon = str(params.get("icon") or "").strip() or None
    color = str(params.get("color") or "").strip() or None

    pid = create_project(
        settings.database_url,
        name,
        project_type,
        description=description,
        lead_agent=lead_agent,
        local_path=local_path,
        icon=icon,
        color=color,
    )
    return ActionResult(
        action="create_project",
        success=True,
        detail=f"Project '{name}' created ({pid[:8]})",
        data={"project_id": pid, "name": name},
    )


# -------------------------------------------------------------------
# Pre-execution parameter validation gate
# -------------------------------------------------------------------

# Patterns that indicate hallucinated / placeholder values

_PLACEHOLDER_RE = _re.compile(
    r"^<[\w_]+>$"  # "<task_id>", "<message_id>"
    r"|^{[\w_]+}$"  # "{task_id}"
    r"|^\[[\w_]+\]$"  # "[task_id]"
    r"|^placeholder$"
    r"|^example$"
    r"|^test$"
    r"|^TODO$",
    _re.IGNORECASE,
)

# Per-action ID param validation rules.
# key = action_name, value = list of (param_name, min_length)
_ID_PARAM_RULES: dict[str, list[tuple[str, int]]] = {
    "gmail_read": [("id", 6), ("message_id", 6)],
    "gmail_send": [("to", 3)],
    "gmail_draft": [("to", 3)],
    "update_task": [("id", 1), ("task_id", 1)],
    "close_task": [("id", 1), ("task_id", 1)],
    "assign_task": [("id", 1), ("task_id", 1)],
    "calendar_update": [("event_id", 4)],
    "calendar_delete": [("event_id", 4)],
    "ha_call_service": [("service", 3)],
    "github_read_file": [("path", 1)],
    "github_write_file": [("path", 1)],
}


def _validate_params(
    action_name: str,
    params: dict[str, str],
) -> ActionResult | None:
    """Return an ActionResult for obviously bad params, or None if ok.

    This is a soft-fail: returns success=False but does NOT call
    record_failure, so it won't trigger autonomy demotions. The LLM
    gets a clear error message and can retry with valid values.
    """
    rules = _ID_PARAM_RULES.get(action_name)
    if not rules:
        return None

    for param_name, min_len in rules:
        val = str(params.get(param_name, "")).strip()
        if not val:
            continue  # Missing param handled by the executor
        # Check for placeholder patterns
        if _PLACEHOLDER_RE.match(val):
            return ActionResult(
                action=action_name,
                success=False,
                detail=(
                    f"Bad parameter '{param_name}': "
                    f"'{val}' looks like a placeholder. "
                    f"Use a real value from prior tool "
                    f"results."
                ),
            )
        # Check for obviously too-short IDs
        # (e.g., gmail_read(id="1") — real Gmail IDs are 16+ hex chars)
        if len(val) < min_len:
            return ActionResult(
                action=action_name,
                success=False,
                detail=(
                    f"Bad parameter '{param_name}': "
                    f"'{val}' is too short (min {min_len})."
                    f" Use a real ID from prior results."
                ),
            )
        # Numeric-only ID for Gmail (real Gmail IDs are hex strings)
        if action_name.startswith("gmail_") and (param_name in ("id", "message_id")):
            if val.isdigit() and len(val) < 10:
                return ActionResult(
                    action=action_name,
                    success=False,
                    detail=(
                        f"Bad parameter '{param_name}': "
                        f"'{val}' is not a valid Gmail "
                        f"message ID. Gmail IDs are long "
                        f"hex strings like '18e5a3b2c1d4e5f6'."
                        f" Use gmail_list first."
                    ),
                )

    return None


def _is_policy_refusal(result: Any) -> bool:
    """True when this result is a POLICY REFUSAL: the action never ran.

    One predicate, read by every consumer that must not punish an agent for
    obeying the rules -- the retry loop, the circuit breaker, and
    `agent_worker._execute_tool_dispatch`'s tool-strike counter. It is set by the
    two places that can refuse deliberately: the autonomy gate in
    `_dispatch_action` and the deterministic policy gate in
    `app/chat_action_policy._enforce_action_policy`.

    "No answer" and "an answer that never closed" are different sentences: a
    refusal is a *decision*, and a decision made on purpose is not evidence that
    the action is unsafe or broken. Before 2026-10-26 the refusal was returned as
    a plain `success=False`, so every consumer read it as a failure: it was
    retried 3x, it counted a tool strike, `TOOL_LOOP_DEADLOCK` fired, and the step
    ended having done nothing.
    """
    data = getattr(result, "data", None)
    return bool(isinstance(data, dict) and data.get("policy_refused"))


def _policy_refusal_key(
    action_name: str,
    agent_id: str,
    action_params: dict[str, str] | None,
    *,
    kind: str = "autonomy",
) -> str:
    """Exact dedupe key for ONE (action, agent, resource) refusal.

    `database.create_task` already dedupes -- by fuzzy title at 80% similarity,
    agent-agnostic, and by `dedupe_key` when given one (exact, via
    `idx_task_dedupe_key`). Fuzzy title is the wrong key here: it ignores the
    resource, so `repo_read_file` on two different paths collapses onto one
    approval task, and it re-matches an unrelated title that happens to read the
    same. The resource is the parameters, hashed so the key stays short and does
    not carry a path into a task row.
    """
    resource = {
        str(k): str(v)
        for k, v in (action_params or {}).items()
        if str(k) != "_action"
    }
    digest = hashlib.sha256(
        json.dumps(resource, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()[:12]
    return f"policy-refusal:{kind}:{action_name}:{agent_id or '-'}:{digest}"


def _dispatch_action(
    action_name: str,
    action_params: dict[str, str],
    *,
    settings: Any,
    agent_id: str,
) -> ActionResult:
    """Route an action to its executor. No retries here."""
    # Normalize parameters before dispatch
    action_params = _normalize_params(
        action_name,
        action_params,
    )

    # ── Pre-execution parameter validation gate ──
    # Reject obviously hallucinated params before they reach the
    # executor and trigger autonomy record_failure / demotion.
    # Returns a soft-fail ActionResult so the LLM can retry.
    validation_err = _validate_params(action_name, action_params)
    if validation_err is not None:
        return validation_err

    policy_blocked = _enforce_action_policy(
        action_name,
        action_params,
        settings=settings,
        agent_id=agent_id,
        create_approval_task=_create_approval_task,
    )
    if policy_blocked is not None:
        return policy_blocked

    # ── Operation journal: start tracking ──
    op_id: int | None = None
    try:
        from app.database import start_operation

        db_url = getattr(settings, "database_url", "") or ""
        if db_url:
            op_id = start_operation(
                db_url,
                operation_type=action_name,
                detail=str(action_params)[:500],
                agent_id=agent_id,
            )
    except Exception:
        pass  # Never let journaling break execution

    # ── Autonomy level check ──
    try:
        from app.services.autonomy import (
            record_failure as _auto_fail,
            record_success as _auto_ok,
            should_execute,
        )

        decision = should_execute(action_name, settings)
        _autonomy_action = decision.get("action", "execute")
        _autonomy_execute = bool(decision.get("execute", False))
        _autonomy_level_name = decision.get("level_name", "UNKNOWN")
        _autonomy_reason = decision.get("reason", "")
    except Exception:
        # FAIL CLOSED: a gate that cannot be consulted must not grant execution.
        _autonomy_action = "suggest"
        _autonomy_execute = False
        _autonomy_level_name = "L1_SUGGEST"
        _autonomy_reason = "the autonomy gate could not be consulted"

    # --- Autonomy verdict: it must reach a branch, not only a variable ---
    # should_execute() returns execute=False for L0/L1/L2. Until this, the verdict was
    # stored in _autonomy_action and the action dispatched regardless.
    if not _autonomy_execute:
        # ── POLICY REFUSAL, NOT A FAILURE (2026-10-26) ──
        # The gate decided this on purpose: the action never ran, so it cannot have
        # failed, and attempting it again cannot change the answer. Everything
        # downstream must read that the same way, or the refusal punishes the agent
        # for obeying policy. `data["policy_refused"]` is the marker they read:
        # `execute_actions()` (no retry, no breaker) and
        # `agent_worker._execute_tool_with_autonomy` (no tool strike, and the step
        # suspends as waiting-on-owner instead of dying as a deadlock).
        _refusal_key = _policy_refusal_key(action_name, agent_id, action_params)
        _approval_task_id = None
        try:
            _approval_task_id = _create_approval_task(
                settings=settings,
                title=f"Approve action: {action_name}",
                description=(
                    f"The autonomy gate resolved '{action_name}' to "
                    f"{_autonomy_level_name} - {_autonomy_reason}. Nothing was "
                    f"executed and nothing is broken: this is a policy refusal, "
                    f"waiting on owner. Proposed parameters: "
                    f"{str(action_params)[:400]}"
                ),
                tags=["approval", "autonomy", action_name],
                dedupe_key=_refusal_key,
            )
        except Exception:
            _approval_task_id = None
        _refusal_detail = (
            f"NOT EXECUTED - '{action_name}' requires owner approval "
            f"({_autonomy_level_name}: {_autonomy_reason}). This is a policy "
            f"refusal, not a failure: the action did not run, so it cannot have "
            f"failed, and repeating it cannot change the answer. "
            + (
                f"Waiting on owner - approval task {_approval_task_id}."
                if _approval_task_id
                else "An approval task could not be queued; nothing ran."
            )
        )
        log.info(
            "POLICY_REFUSED action=%s agent=%s level=%s reason=%s task=%s key=%s",
            action_name,
            agent_id or "-",
            _autonomy_level_name,
            _autonomy_reason,
            _approval_task_id if _approval_task_id is not None else "-",
            _refusal_key,
        )
        return ActionResult(
            action=action_name,
            success=False,
            detail=_refusal_detail,
            data={
                "policy_refused": True,
                "policy_refusal_kind": "autonomy_gate",
                "approval_task_id": _approval_task_id,
                "autonomy_level": _autonomy_level_name,
                "autonomy_reason": _autonomy_reason,
                "dedupe_key": _refusal_key,
            },
        )

    # Execute the action
    try:
        result = _dispatch_action_inner(
            action_name,
            action_params,
            settings=settings,
            agent_id=agent_id,
        )

        # ── Operation journal: complete ──
        if op_id is not None:
            try:
                from app.database import complete_operation

                db_url = getattr(settings, "database_url", "") or ""
                if db_url:
                    complete_operation(
                        db_url,
                        op_id,
                        result_summary=str(result.detail)[:500],
                    )
            except Exception:
                pass

        # ── Autonomy: record success ──
        if result.success:
            try:
                _auto_ok(action_name, settings)
            except Exception:
                pass
        else:
            # Name the cause at the moment the counter moves. On 2026-10-26 a
            # session read "Autonomy DEMOTED: repo_read_file L4 → L3" and
            # attributed it to policy refusals; it could not check, because the
            # reason was never logged -- and a refusal logs nothing here at all
            # (the refusal branch returns above this line). An unattributable
            # demotion is an invitation to invent one.
            try:
                _auto_fail(action_name, settings)
                log.info(
                    "Autonomy: recorded a real execution failure for %s: %s",
                    action_name,
                    str(result.detail)[:200],
                )
            except Exception:
                pass

        return result

    except Exception as exc:
        # ── Operation journal: fail ──
        if op_id is not None:
            try:
                from app.database import fail_operation

                db_url = getattr(settings, "database_url", "") or ""
                if db_url:
                    fail_operation(db_url, op_id, str(exc)[:500])
            except Exception:
                pass
        # ── Autonomy: record failure ──
        try:
            _auto_fail(action_name, settings)
        except Exception:
            pass
        raise


def _dispatch_action_inner(
    action_name: str,
    action_params: dict[str, str],
    *,
    settings: Any,
    agent_id: str,
) -> ActionResult:
    """Inner dispatch — routes to specific action executors."""

    if action_name == "system_health":
        return _exec_system_health(
            action_params,
            settings=settings,
        )
    if action_name == "read_local_repo_file":
        return _exec_read_local_repo_file(action_params)
    if action_name == "send_sms":
        return _exec_send_sms(
            action_params,
            settings=settings,
        )
    if action_name == "dialpad_send_sms":
        from app.chat_action_phone_tech import _exec_dialpad_send_sms

        return _exec_dialpad_send_sms(
            action_params,
            settings=settings,
        )
    if action_name == "stripe_search_charges":
        from app.services.stripe_service import search_charges
        from datetime import datetime, timedelta, timezone

        days = int(action_params.get("days", 60))
        amount_dollars = action_params.get("amount_dollars") or action_params.get(
            "amount"
        )
        last4 = action_params.get("last4") or action_params.get("card_last4")
        limit = int(action_params.get("limit", 20))

        amount_cents = (
            int(round(float(amount_dollars) * 100)) if amount_dollars else None
        )
        since = datetime.now(tz=timezone.utc) - timedelta(days=days)
        charges = search_charges(
            settings,
            amount_cents=amount_cents,
            last4=str(last4) if last4 else None,
            created_after=since,
            limit=limit,
        )
        summary = [
            f"{c['created_dt'][:10]}  ${c['amount_dollars']:.2f}  {c['status']}  "
            f"****{c['card_last4']}  {c['description'] or '(no desc)'}"
            for c in charges
        ]
        return ActionResult(
            success=True,
            action="stripe_search_charges",
            detail=(
                f"Found {len(charges)} charge(s):\n" + "\n".join(summary)
                if charges
                else "No charges found."
            ),
            data={"charges": charges, "count": len(charges)},
        )
    if action_name == "create_task":
        return _exec_create_task(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "create_project":
        return _exec_create_project(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "save_memory":
        return _exec_save_memory(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "web_search":
        return _exec_web_search(
            action_params,
            settings=settings,
        )
    if action_name == "ask_advisor":
        return _exec_ask_advisor(
            action_params,
            settings=settings,
        )
    if action_name == "deep_research":
        return _exec_deep_research(
            action_params,
            settings=settings,
        )
    if action_name == "build_tool":
        return _exec_build_tool(
            action_params,
            settings=settings,
        )
    if action_name == "list_skills":
        return _exec_list_skills(action_params)
    if action_name == "import_skill":
        return _exec_import_skill(
            action_params,
            settings=settings,
        )
    if action_name == "hire_department":
        return _exec_hire_department(
            action_params,
            settings=settings,
        )
    if action_name == "fire_agent":
        return _exec_fire_agent(
            action_params,
            settings=settings,
        )
    if action_name == "reactivate_agent":
        return _exec_reactivate_agent(
            action_params,
            settings=settings,
        )
    if action_name == "delegate_task":
        return _exec_delegate_task(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "send_directive":
        return _exec_send_directive(
            action_params,
            settings=settings,
        )
    if action_name == "fetch_url":
        return _exec_fetch_url(action_params)
    if action_name == "code_edit":
        return _exec_code_edit(
            action_params,
            settings=settings,
        )
    if action_name == "upgrade_tool":
        return _exec_upgrade_tool(
            action_params,
            settings=settings,
        )
    if action_name == "delete_tool":
        return _exec_delete_tool(action_params)
    if action_name == "list_dynamic_tools":
        return _exec_list_dynamic_tools(action_params)
    if action_name == "get_current_datetime":
        return _exec_get_current_datetime(action_params)
    if action_name == "schedule_reminder":
        return _exec_schedule_reminder(
            action_params,
            settings=settings,
        )
    # ── Ask the Boss / Mission actions ──
    if action_name == "ask_owner":
        return _exec_ask_owner(
            action_params,
            settings=settings,
        )
    if action_name == "propose_owner_assumption":
        return _exec_propose_owner_assumption(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "propose_spend_request":
        return _exec_propose_spend_request(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "propose_human_job":
        return _exec_propose_human_job(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "propose_mission":
        return _exec_propose_mission(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "list_missions":
        return _exec_list_missions(
            action_params,
            settings=settings,
        )
    if action_name == "update_mission":
        return _exec_update_mission(
            action_params,
            settings=settings,
        )
    if action_name == "schedule_action":
        return _exec_schedule_action(
            action_params,
            settings=settings,
        )
    # ── Workflow / Goal actions ──
    if action_name == "create_goal":
        return _exec_create_goal(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "complete_goal_step":
        return _exec_complete_goal_step(
            action_params,
            settings=settings,
        )
    if action_name == "pause_goal":
        return _exec_pause_goal(
            action_params,
            settings=settings,
        )
    if action_name == "cancel_goal":
        return _exec_cancel_goal(
            action_params,
            settings=settings,
        )
    # ── Google Calendar actions ──
    if action_name == "calendar_list":
        return _exec_calendar_list(
            action_params,
            settings=settings,
        )
    if action_name == "calendar_create":
        return _exec_calendar_create(
            action_params,
            settings=settings,
        )
    if action_name == "calendar_update":
        return _exec_calendar_update(
            action_params,
            settings=settings,
        )
    if action_name == "calendar_delete":
        return _exec_calendar_delete(
            action_params,
            settings=settings,
        )
    if action_name == "calendar_get":
        return _exec_calendar_get(
            action_params,
            settings=settings,
        )
    if action_name == "calendar_list_calendars":
        return _exec_calendar_list_calendars(
            action_params,
            settings=settings,
        )
    # ── Gmail actions ──
    if action_name == "gmail_list":
        return _exec_gmail_list(
            action_params,
            settings=settings,
        )
    if action_name == "gmail_read":
        return _exec_gmail_read(
            action_params,
            settings=settings,
        )
    if action_name == "gmail_search":
        return _exec_gmail_search(
            action_params,
            settings=settings,
        )
    if action_name == "gmail_send":
        return _exec_gmail_send(
            action_params,
            settings=settings,
        )
    if action_name == "gmail_draft":
        return _exec_gmail_draft(
            action_params,
            settings=settings,
        )
    if action_name == "gmail_accounts":
        return _exec_gmail_accounts(
            action_params,
            settings=settings,
        )
    # ── QuickBooks actions ──
    if action_name == "qb_status":
        return _exec_qb_status(
            action_params,
            settings=settings,
        )
    if action_name == "qb_snapshot":
        return _exec_qb_snapshot(
            action_params,
            settings=settings,
        )
    if action_name == "ledger_source_registry":
        return _exec_ledger_source_registry(
            action_params,
            settings=settings,
        )
    if action_name == "ledger_status":
        return _exec_ledger_status(
            action_params,
            settings=settings,
        )
    if action_name == "qb_reconciliation":
        return _exec_qb_reconciliation(
            action_params,
            settings=settings,
        )
    if action_name == "qb_query":
        return _exec_qb_query(
            action_params,
            settings=settings,
        )
    if action_name == "qb_search":
        return _exec_qb_search(
            action_params,
            settings=settings,
        )
    if action_name == "qb_accounts":
        return _exec_qb_accounts(
            action_params,
            settings=settings,
        )
    if action_name == "qb_vendors":
        return _exec_qb_vendors(
            action_params,
            settings=settings,
        )
    # ── Home Assistant actions ──
    if action_name == "ha_status":
        return _exec_ha_status(
            action_params,
            settings=settings,
        )
    if action_name == "ha_states":
        return _exec_ha_states(
            action_params,
            settings=settings,
        )
    if action_name == "ha_entity":
        return _exec_ha_entity(
            action_params,
            settings=settings,
        )
    if action_name == "ha_call_service":
        return _exec_ha_call_service(
            action_params,
            settings=settings,
        )
    if action_name == "ha_doors":
        return _exec_ha_doors(
            action_params,
            settings=settings,
        )
    if action_name == "ha_climate":
        return _exec_ha_climate(
            action_params,
            settings=settings,
        )
    if action_name == "ha_security":
        return _exec_ha_security(
            action_params,
            settings=settings,
        )
    # ── Semantic memory actions ──
    # ── Browser automation actions ──
    if action_name == "browser_goto":
        return _exec_browser_goto(
            action_params,
            settings=settings,
        )
    if action_name == "browser_click":
        return _exec_browser_click(
            action_params,
            settings=settings,
        )
    if action_name == "browser_fill":
        return _exec_browser_fill(
            action_params,
            settings=settings,
        )
    if action_name == "browser_screenshot":
        return _exec_browser_screenshot(
            action_params,
            settings=settings,
        )
    if action_name == "browser_run":
        return _exec_browser_run(
            action_params,
            settings=settings,
        )
    if action_name == "browser_sessions":
        return _exec_browser_sessions(
            action_params,
            settings=settings,
        )
    if action_name == "browser_save_session":
        return _exec_browser_save_session(
            action_params,
            settings=settings,
        )
    if action_name == "browser_act":
        return _exec_browser_act(
            action_params,
            settings=settings,
        )
    if action_name == "browser_use_run":
        return _exec_browser_use_run(
            action_params,
            settings=settings,
        )
    if action_name == "browser_session_list":
        return _exec_browser_session_list(
            action_params,
            settings=settings,
        )
    if action_name == "browser_session_delete":
        return _exec_browser_session_delete(
            action_params,
            settings=settings,
        )
    if action_name == "browser_capture_session":
        return _exec_browser_capture_session(
            action_params,
            settings=settings,
        )
    if action_name == "cua_run":
        return _exec_cua_run(
            action_params,
            settings=settings,
        )
    if action_name == "gv_send_sms":
        return _exec_gv_send_sms(
            action_params,
            settings=settings,
        )
    if action_name == "gv_read_messages":
        return _exec_gv_read_messages(
            action_params,
            settings=settings,
        )
    if action_name == "gv_read_conversation":
        return _exec_gv_read_conversation(
            action_params,
            settings=settings,
        )
    if action_name == "gv_read_calls":
        return _exec_gv_read_calls(
            action_params,
            settings=settings,
        )
    if action_name == "gv_read_voicemails":
        return _exec_gv_read_voicemails(
            action_params,
            settings=settings,
        )
    if action_name == "memory_search":
        return _exec_memory_search(
            action_params,
            settings=settings,
        )
    if action_name == "memory_save":
        return _exec_memory_save(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "memory_sync":
        return _exec_memory_sync(
            action_params,
            settings=settings,
        )
    if action_name == "memory_stats":
        return _exec_memory_stats(
            action_params,
            settings=settings,
        )
    # ── Managed Workflows ──
    if action_name == "managed_workflow_status":
        from app.chat_action_managed_workflows import _exec_managed_workflow_status

        return _exec_managed_workflow_status(
            action_params,
            settings=settings,
        )
    if action_name == "managed_workflow_report":
        from app.chat_action_managed_workflows import _exec_managed_workflow_report

        return _exec_managed_workflow_report(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    # ── Phone & Tech integrations ──
    if action_name == "dialpad_pull_calls":
        from app.chat_action_phone_tech import _exec_dialpad_pull_calls

        return _exec_dialpad_pull_calls(
            action_params,
            settings=settings,
        )
    if action_name == "dialpad_pull_sms":
        from app.chat_action_phone_tech import _exec_dialpad_pull_sms

        return _exec_dialpad_pull_sms(
            action_params,
            settings=settings,
        )
    if action_name == "dialpad_deep_harvest":
        from app.chat_action_phone_tech import _exec_dialpad_deep_harvest

        return _exec_dialpad_deep_harvest(
            action_params,
            settings=settings,
        )
    if action_name == "read_call_transcript":
        from app.chat_action_phone_tech import _exec_read_call_transcript

        return _exec_read_call_transcript(
            action_params,
            settings=settings,
        )
    if action_name == "daily_reconciliation_run":
        from app.services.daily_reconciliation import (
            run_daily_reconciliation,
        )

        result = run_daily_reconciliation(
            settings=settings, trigger=action_params.get("trigger") or "manual"
        )
        return ActionResult(
            action=action_name,
            success=bool(result.get("ok")),
            detail=(
                result.get("summary")
                or result.get("error")
                or "reconciliation complete"
            ),
            data=result,
        )
    if action_name == "website_push_dialpad_intelligence":
        from app.chat_action_phone_tech import (
            _exec_website_push_dialpad_intelligence,
        )

        return _exec_website_push_dialpad_intelligence(
            action_params,
            settings=settings,
        )
    if action_name == "lpt_hub_sync_cases":
        from app.chat_action_phone_tech import _exec_lpt_hub_sync_cases

        return _exec_lpt_hub_sync_cases(
            action_params,
            settings=settings,
        )
    if action_name == "website_push_sync":
        from app.chat_action_phone_tech import _exec_website_push_sync

        return _exec_website_push_sync(
            action_params,
            settings=settings,
        )
    if action_name == "lpt_hub_classify_cases":
        from app.chat_action_phone_tech import _exec_lpt_hub_classify_cases

        return _exec_lpt_hub_classify_cases(
            action_params,
            settings=settings,
        )
    if action_name == "website_push_reconciliation":
        from app.chat_action_phone_tech import (
            _exec_website_push_reconciliation,
        )

        return _exec_website_push_reconciliation(
            action_params,
            settings=settings,
        )
    if action_name == "website_db_sync":
        return _exec_website_db_sync(
            action_params,
            settings=settings,
        )
    if action_name == "website_pricing_summary":
        from app.chat_action_phone_tech import _exec_website_pricing_summary

        return _exec_website_pricing_summary(
            action_params,
            settings=settings,
        )
    if action_name == "pricing_lookup":
        from app.chat_action_phone_tech import _exec_pricing_lookup

        return _exec_pricing_lookup(
            action_params,
            settings=settings,
        )
    if action_name == "website_work_order_digest":
        from app.chat_action_phone_tech import (
            _exec_website_work_order_digest,
        )

        return _exec_website_work_order_digest(
            action_params,
            settings=settings,
        )
    if action_name == "open_work_order_reconciliation":
        from app.chat_action_phone_tech import (
            _exec_open_work_order_reconciliation,
        )

        return _exec_open_work_order_reconciliation(
            action_params,
            settings=settings,
        )
    if action_name == "create_customer":
        from app.chat_action_phone_tech import _exec_create_customer

        return _exec_create_customer(
            action_params,
            settings=settings,
        )
    if action_name == "create_work_order":
        from app.chat_action_phone_tech import _exec_create_work_order

        return _exec_create_work_order(
            action_params,
            settings=settings,
        )
    # ── Shop Operations actions ──
    if action_name == "shop_customer_intake":
        from app.services.shop_ops import customer_intake

        result = customer_intake(
            settings,
            customer_name=action_params.get("customer_name", ""),
            customer_phone=action_params.get("customer_phone", ""),
            device_make=action_params.get("device_make", ""),
            device_model=action_params.get("device_model", ""),
            issue_description=action_params.get("issue_description", ""),
            customer_email=action_params.get("customer_email"),
            device_serial=action_params.get("device_serial"),
            source=action_params.get("source", "walk-in"),
        )
        if result.get("ok"):
            return ActionResult(
                success=True,
                action="shop_customer_intake",
                detail=(
                    f"Intake complete: contact #{result['contact_id']}, "
                    f"task #{result['task_id']}, case {result.get('case_id', '?')}"
                ),
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_customer_intake",
            detail=result.get("error", "Intake failed"),
            data=result,
        )
    if action_name == "shop_update_repair_status":
        from app.services.shop_ops import update_repair_status

        result = update_repair_status(
            settings,
            task_id=int(action_params.get("task_id", 0)),
            new_status=action_params.get("new_status", ""),
            notes=action_params.get("notes"),
            send_sms=action_params.get("send_sms", "").lower() in {"1", "true", "yes"},
            sms_custom_message=action_params.get("sms_custom_message"),
        )
        if result.get("ok"):
            detail = (
                f"Repair #{result['task_id']}: {result.get('previous_status', '?')}"
                f" → {result['new_status']}"
            )
            if result.get("sms_result", {}).get("ok"):
                detail += " (SMS sent)"
            return ActionResult(
                success=True,
                action="shop_update_repair_status",
                detail=detail,
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_update_repair_status",
            detail=result.get("error", "Status update failed"),
            data=result,
        )
    if action_name == "shop_list_repairs":
        from app.services.shop_ops import get_repair_status_summary

        result = get_repair_status_summary(
            settings,
            status_filter=action_params.get("status"),
            limit=int(action_params.get("limit", 50)),
        )
        if result.get("ok"):
            counts = result.get("status_counts", {})
            summary = ", ".join(f"{k}: {v}" for k, v in counts.items())
            return ActionResult(
                success=True,
                action="shop_list_repairs",
                detail=f"{result['total']} repair(s): {summary}",
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_list_repairs",
            detail=result.get("error", "Failed to list repairs"),
            data=result,
        )
    if action_name == "shop_add_part":
        from app.services.shop_ops import add_part

        result = add_part(
            settings,
            name=action_params.get("name", ""),
            part_number=action_params.get("part_number", ""),
            category=action_params.get("category", "general"),
            compatible_devices=action_params.get("compatible_devices", ""),
            quantity=int(action_params.get("quantity", 0)),
            min_quantity=int(action_params.get("min_quantity", 1)),
            unit_cost=float(action_params.get("unit_cost", 0.0)),
            supplier=action_params.get("supplier", ""),
            supplier_url=action_params.get("supplier_url", ""),
            notes=action_params.get("notes", ""),
        )
        if result.get("ok"):
            return ActionResult(
                success=True,
                action="shop_add_part",
                detail=f"Part added: #{result['part_id']}",
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_add_part",
            detail=result.get("error", "Failed to add part"),
            data=result,
        )
    if action_name == "shop_list_parts":
        from app.services.shop_ops import list_parts

        result = list_parts(
            settings,
            category=action_params.get("category"),
            low_stock_only=action_params.get("low_stock", "").lower() in {"1", "true", "yes"},
            query=action_params.get("query", ""),
            limit=int(action_params.get("limit", 50)),
        )
        if result.get("ok"):
            detail = f"{result['total']} part(s)"
            if result.get("low_stock_count"):
                detail += f", {result['low_stock_count']} low stock"
            return ActionResult(
                success=True,
                action="shop_list_parts",
                detail=detail,
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_list_parts",
            detail=result.get("error", "Failed to list parts"),
            data=result,
        )
    if action_name == "shop_link_part":
        from app.services.shop_ops import link_part_to_repair

        result = link_part_to_repair(
            settings,
            task_id=int(action_params.get("task_id", 0)),
            part_id=int(action_params.get("part_id", 0)),
            quantity_used=int(action_params.get("quantity_used", 1)),
        )
        if result.get("ok"):
            return ActionResult(
                success=True,
                action="shop_link_part",
                detail=(
                    f"Linked {result['part_name']} (x{result['quantity_used']}) "
                    f"to task #{result['task_id']} — {result['remaining']} remaining"
                ),
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_link_part",
            detail=result.get("error", "Failed to link part"),
            data=result,
        )
    if action_name == "shop_check_uncollected":
        from app.services.shop_ops import check_uncollected_repairs

        result = check_uncollected_repairs(
            settings,
            days_threshold=int(action_params.get("days_threshold", 3)),
            dry_run=action_params.get("dry_run", "").lower() not in {"0", "false", "no"},
        )
        if result.get("ok"):
            detail = f"{result['total']} uncollected repair(s)"
            if result.get("reminders_sent"):
                detail += f", {result['reminders_sent']} reminder(s) sent"
            if result.get("dry_run"):
                detail += " (dry run)"
            return ActionResult(
                success=True,
                action="shop_check_uncollected",
                detail=detail,
                data=result,
            )
        return ActionResult(
            success=False,
            action="shop_check_uncollected",
            detail=result.get("error", "Check failed"),
            data=result,
        )
    # ── Long-running task & repo management actions ──
    if action_name == "update_task":
        action_params["_agent_id"] = agent_id
        return _exec_update_task(
            action_params,
            settings=settings,
        )
    if action_name == "list_tasks":
        return _exec_list_tasks(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "link_task_to_mission":
        return _exec_link_task_to_mission(
            action_params,
            settings=settings,
        )
    if action_name == "start_work_session":
        return _exec_start_work_session(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "update_progress":
        return _exec_update_progress(
            action_params,
            settings=settings,
        )
    if action_name == "complete_work":
        return _exec_complete_work(
            action_params,
            settings=settings,
        )
    if action_name == "enqueue_job":
        return _exec_enqueue_job(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "github_read_file":
        return _exec_github_read_file(
            action_params,
            settings=settings,
        )
    if action_name == "github_list_dir":
        return _exec_github_list_dir(
            action_params,
            settings=settings,
        )
    if action_name == "github_list_issues":
        return _exec_github_list_issues(
            action_params,
            settings=settings,
        )
    if action_name == "github_create_issue":
        return _exec_github_create_issue(
            action_params,
            settings=settings,
        )
    if action_name == "github_list_prs":
        return _exec_github_list_prs(
            action_params,
            settings=settings,
        )
    if action_name == "repo_read_file":
        return _exec_repo_read_file(action_params)
    if action_name == "repo_list_dir":
        return _exec_repo_list_dir(action_params)
    if action_name == "repo_map":
        return _exec_repo_map(action_params)
    if action_name == "repo_search":
        return _exec_repo_search(action_params)
    if action_name == "repo_run_command":
        return _exec_repo_run_command(action_params)
    if action_name == "close_task":
        # Alias: close_task → update_task with status=done
        action_params["status"] = "done"
        action_params["_agent_id"] = agent_id
        result = _exec_update_task(
            action_params,
            settings=settings,
        )
        detail = result.detail
        if result.success and detail.endswith(" updated"):
            detail = detail[: -len(" updated")] + " closed"
        return ActionResult(
            action="close_task",
            success=result.success,
            detail=detail,
            data=result.data,
        )
    if action_name == "assign_task":
        # Alias: assign_task → update_task
        action_params["_agent_id"] = agent_id
        return _exec_update_task(
            action_params,
            settings=settings,
        )
    if action_name == "consolidate_tasks":
        return _exec_consolidate_tasks(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    if action_name == "task_hygiene":
        return _exec_task_hygiene(
            action_params,
            settings=settings,
            agent_id=agent_id,
        )
    # ── Bulk company hygiene actions ──
    if action_name == "bulk_cancel_failed_goals":
        return _exec_bulk_cancel_failed_goals(
            action_params,
            settings=settings,
        )
    if action_name == "bulk_prune_idle_agents":
        return _exec_bulk_prune_idle_agents(
            action_params,
            settings=settings,
        )
    if action_name == "bulk_close_duplicate_tasks":
        return _exec_bulk_close_duplicate_tasks(
            action_params,
            settings=settings,
        )
    # ── Contact actions ──
    if action_name == "contact_search":
        return _exec_contact_search(
            action_params,
            settings=settings,
        )
    if action_name == "contact_lookup":
        return _exec_contact_lookup(
            action_params,
            settings=settings,
        )
    if action_name == "contact_update":
        return _exec_contact_update(
            action_params,
            settings=settings,
        )
    # ── Owner context actions ──
    if action_name == "owner_vscode_activity":
        return _exec_owner_vscode_activity(action_params)
    # ── Linux recovery PC (SSH) actions ──
    if action_name == "linux_pc_ssh":
        return _exec_linux_pc_ssh(action_params, settings=settings)
    if action_name == "linux_pc_status":
        return _exec_linux_pc_status(action_params, settings=settings)
    if action_name == "linux_pc_list_usb":
        return _exec_linux_pc_list_usb(action_params, settings=settings)
    if action_name == "linux_pc_mount":
        return _exec_linux_pc_mount(action_params, settings=settings)
    if action_name == "linux_pc_unmount":
        return _exec_linux_pc_unmount(action_params, settings=settings)
    # Dynamic tool fallback
    return _exec_dynamic_tool(action_name, action_params)


# Actions safe to retry on failure (idempotent or read-only)
_RETRYABLE_ACTIONS = frozenset(
    {
        "web_search",
        "fetch_url",
        "get_current_datetime",
        "code_edit",
        "build_tool",
        "upgrade_tool",
        "delete_tool",
        "list_dynamic_tools",
        "schedule_reminder",
        "schedule_action",
        "list_tasks",
        "github_read_file",
        "github_list_dir",
        "github_list_issues",
        "github_list_prs",
        "repo_read_file",
        "repo_list_dir",
        "repo_map",
        "repo_search",
        "repo_run_command",
        "system_health",
        "calendar_list",
        "calendar_create",
        "calendar_update",
        "calendar_delete",
        "calendar_get",
        "calendar_list_calendars",
        "gmail_list",
        "gmail_read",
        "gmail_search",
        "gmail_send",
        "gmail_draft",
        "gmail_accounts",
        "qb_status",
        "qb_snapshot",
        "qb_reconciliation",
        "qb_query",
        "qb_search",
        "qb_accounts",
        "qb_vendors",
        "ha_status",
        "ha_states",
        "ha_entity",
        "ha_call_service",
        "ha_doors",
        "ha_climate",
        "ha_security",
        "memory_search",
        "memory_save",
        "memory_sync",
        "memory_stats",
        "managed_workflow_status",
        "browser_goto",
        "browser_click",
        "browser_fill",
        "browser_screenshot",
        "browser_run",
        "browser_sessions",
        "browser_save_session",
        "browser_act",
        "browser_use_run",
        "browser_session_list",
        "browser_session_delete",
        "browser_capture_session",
        "cua_run",
        "gv_send_sms",
        "gv_read_messages",
        "gv_read_conversation",
        "gv_read_calls",
        "gv_read_voicemails",
        "owner_vscode_activity",
    }
)


def execute_actions(
    actions: list[dict[str, str]],
    *,
    settings: Any,
    agent_id: str,
) -> list[ActionResult]:
    """Execute parsed actions with retry and circuit breaker.

    Resilience features:
      - Circuit breaker: if an action type fails repeatedly,
        it is temporarily disabled with a clear message
      - Retry: idempotent actions are retried up to
        _MAX_ACTION_RETRIES times with backoff
      - Detailed error context: every failure includes the
        full error message so the agent can diagnose/adapt
      - Graceful continuation: one action failure doesn't
        block execution of subsequent actions
    """
    results: list[ActionResult] = []

    def _trace_result(
        action_name: str,
        action_params: dict[str, str],
        result: ActionResult,
    ) -> None:
        with langfuse_span(
            settings,
            name="tool_action",
            input_payload={
                "action": action_name,
                "params": action_params,
            },
            metadata={"agent_id": agent_id},
        ) as tool_obs:
            langfuse_update(
                tool_obs,
                output=result.detail,
                metadata={
                    "action": action_name,
                    "success": bool(result.success),
                },
                level=("ERROR" if not result.success else None),
            )

    for action_params in actions:
        action_name = action_params.get("_action", "")

        # ── Circuit breaker check ──────────────────────
        if _cb_is_open(action_name):
            log.warning(
                "Action %s skipped: circuit breaker open",
                action_name,
            )
            # Build actionable hint for the agent
            hint = _get_fix_hint(action_name)
            results.append(
                ActionResult(
                    action=action_name,
                    success=False,
                    detail=(
                        f'Action "{action_name}" is temporarily '
                        f"disabled due to repeated failures "
                        f"({_CB_THRESHOLD} consecutive). "
                        f"Will retry automatically after "
                        f"{_CB_COOLDOWN:.0f}s cooldown. "
                        f"{hint}"
                    ),
                    data={"circuit_breaker": "open"},
                )
            )
            _trace_result(action_name, action_params, results[-1])
            continue

        # ── Determine retry count ──────────────────────
        retries = _MAX_ACTION_RETRIES if action_name in _RETRYABLE_ACTIONS else 0

        result: ActionResult | None = None
        last_error = ""

        for attempt in range(retries + 1):
            try:
                result = _dispatch_action(
                    action_name,
                    action_params,
                    settings=settings,
                    agent_id=agent_id,
                )
                if result.success:
                    _record_policy_success(
                        action_name,
                        action_params,
                    )
                    _cb_record_success(action_name)
                    break
                # Action returned failure (not exception)
                last_error = result.detail
                if _is_policy_refusal(result):
                    # A refusal is deterministic -- the same gate answers the same
                    # way on attempt 2 and 3. Retrying it multiplies the log, the
                    # refusal count and the wall clock, and on this estate it also
                    # re-queued the approval task on every attempt.
                    break
                if attempt < retries and _should_retry_action_failure(
                    action_name,
                    last_error,
                ):
                    wait = _RETRY_BACKOFF * (attempt + 1)
                    log.info(
                        "Action %s failed (attempt %d), " "retrying in %.1fs: %s",
                        action_name,
                        attempt + 1,
                        wait,
                        last_error,
                    )
                    time.sleep(wait)
            except Exception as exc:  # noqa: BLE001
                last_error = str(exc)
                log.error(
                    "Action %s raised (attempt %d/%d): %s",
                    action_name,
                    attempt + 1,
                    retries + 1,
                    exc,
                )
                result = ActionResult(
                    action=action_name,
                    success=False,
                    detail=f"Error: {exc}",
                )
                if attempt < retries:
                    wait = _RETRY_BACKOFF * (attempt + 1)
                    time.sleep(wait)

        # If all attempts failed, record in circuit breaker
        if result and not result.success:
            # A policy refusal never ran, so it is not evidence the action is
            # broken. Counting it here would open the breaker at 10 consecutive
            # refusals and disable the action for the whole process -- after which
            # the agent is told the action is "temporarily disabled due to repeated
            # failures", which is the same falsehood in a different costume.
            if not _is_policy_refusal(
                result
            ) and _should_record_circuit_breaker_failure(action_name, last_error):
                _cb_record_failure(action_name)
            # Enrich error detail for agent diagnosis
            if retries > 0 and attempt > 0:  # noqa: F821
                result.detail = (
                    f"{last_error} "
                    f"(failed after {attempt + 1} attempts)"  # noqa: F821
                )

        if result:
            results.append(result)
            _trace_result(action_name, action_params, result)

    langfuse_flush(settings)

    return results


def format_action_results(results: list[ActionResult]) -> str:
    """Format action results into a brief status line for the user."""
    if not results:
        return ""

    parts: list[str] = []
    for r in results:
        if r is None:
            continue
        icon = "✅" if r.success else "❌"
        if r.action == "send_sms":
            to = r.data.get("to", "?")
            parts.append(
                f"{icon} SMS sent to {to}"
                if r.success
                else f"{icon} SMS failed: {r.detail}"
            )
        elif r.action == "create_task":
            title = r.data.get("title", "?")
            parts.append(
                f"{icon} Task created: {title}"
                if r.success
                else f"{icon} Task creation failed: {r.detail}"
            )
        elif r.action == "save_memory":
            parts.append(
                f"{icon} Memory saved"
                if r.success
                else f"{icon} Memory save failed: {r.detail}"
            )
        elif r.action == "web_search":
            parts.append(
                f"{icon} Web search done"
                if r.success
                else f"{icon} Search failed: {r.detail}"
            )
        elif r.action == "get_current_datetime":
            parts.append(
                (
                    f"{icon} Now: {r.detail}"
                    if r.success
                    else f"{icon} Datetime failed: {r.detail}"
                ),
            )
        elif r.action == "schedule_reminder":
            parts.append(
                (
                    f"{icon} Reminder scheduled: {r.detail}"
                    if r.success
                    else f"{icon} Reminder failed: {r.detail}"
                ),
            )
        elif r.action == "schedule_action":
            parts.append(
                (
                    f"{icon} Action scheduled: {r.detail}"
                    if r.success
                    else f"{icon} Schedule failed: {r.detail}"
                ),
            )
        elif r.action.startswith("calendar_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action.startswith("gmail_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action.startswith("qb_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action.startswith("ha_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action.startswith("memory_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action.startswith("browser_"):
            label = r.action.replace("_", " ").title()
            parts.append(
                (
                    f"{icon} {label}: {r.detail}"
                    if r.success
                    else f"{icon} {label} failed: {r.detail}"
                ),
            )
        elif r.action == "update_task":
            parts.append(
                (
                    f"{icon} {r.detail}"
                    if r.success
                    else f"{icon} Task update failed: {r.detail}"
                ),
            )
        elif r.action == "close_task":
            parts.append(
                (
                    f"{icon} {r.detail}"
                    if r.success
                    else f"{icon} Task close failed: {r.detail}"
                ),
            )
        elif r.action == "list_tasks":
            count = r.data.get("count", 0) if r.data else 0
            parts.append(f"{icon} {count} task(s) found")
        elif r.action == "repo_search":
            if r.success:
                matches = r.data.get("matches", []) if r.data else []
                query = str(r.data.get("query", "") or "") if r.data else ""
                match_count = len(matches) if isinstance(matches, list) else 0
                if match_count:
                    parts.append(
                        f'{icon} Repository search found {match_count} match(es) for "{query}"'
                    )
                else:
                    parts.append(
                        f'{icon} Repository search found no matches for "{query}"'
                    )
            else:
                detail_l = (r.detail or "").lower()
                if "repo_path" in detail_l:
                    parts.append(
                        "I need the repository name or path before I can search it."
                    )
                elif "query" in detail_l:
                    parts.append(
                        "I need the search text before I can search the repository."
                    )
                else:
                    parts.append(f"{icon} Repository search failed: {r.detail}")
        elif r.action == "start_work_session":
            parts.append(
                (
                    f"{icon} Work started: {r.detail}"
                    if r.success
                    else f"{icon} Work session failed: {r.detail}"
                ),
            )
        elif r.action == "update_progress":
            parts.append(f"{icon} Progress: {r.detail}")
        elif r.action == "complete_work":
            parts.append(
                (
                    f"{icon} Work completed"
                    if r.success
                    else f"{icon} Complete failed: {r.detail}"
                ),
            )
        elif r.action == "enqueue_job":
            parts.append(
                (
                    f"{icon} Job queued: {r.detail}"
                    if r.success
                    else f"{icon} Queue failed: {r.detail}"
                ),
            )
        elif r.action.startswith("github_"):
            parts.append(f"{icon} {r.action}: {r.detail}")
        elif r.action.startswith("repo_"):
            parts.append(f"{icon} {r.action}: {r.detail}")
        else:
            parts.append(f"{icon} {r.action}: {r.detail}")

    return "\n".join(parts)


# ─── Action Executors ─────────────────────────────────────────


def _exec_send_sms(
    params: dict[str, str],
    *,
    settings: Any,
) -> ActionResult:
    """Send an SMS via Twilio."""
    to = params.get("to", "").strip()
    raw_body = params.get("body", "").strip()

    if not to:
        return ActionResult(
            action="send_sms",
            success=False,
            detail='Missing "to" phone number',
        )
    if not raw_body:
        return ActionResult(
            action="send_sms",
            success=False,
            detail="Missing message body",
        )

    if bool(getattr(settings, "twilio_sms_owner_only", True)):
        try:
            from app.services.owner_notifications import is_owner_number

            to_is_owner = is_owner_number(settings, to)
        except Exception:
            owner = str(getattr(settings, "owner_phone_number", "") or "").strip()
            to_is_owner = bool(owner and to == owner)
        if not to_is_owner:
            return ActionResult(
                action="send_sms",
                success=False,
                detail=(
                    "Twilio SMS is owner-only. Customer/prospect SMS must use "
                    "dialpad_send_sms; do not fall back to Twilio."
                ),
                data={
                    "to": to,
                    "blocked_by": "twilio_sms_owner_only",
                    "required_action": "dialpad_send_sms",
                },
            )

    body = format_agent_sms_body(raw_body, settings=settings)

    # ── Dedup: suppress near-duplicate outbound SMS within 10 min ──
    if _sms_is_duplicate(to, body):
        log.info(
            "SMS dedup: suppressed duplicate to %s",
            to,
        )
        return ActionResult(
            action="send_sms",
            success=True,
            detail=f"Suppressed duplicate to {to}",
            data={"to": to, "dedup": True},
        )

    # ── Owner SMS rate limit: max 2 per day (UTC) ──
    try:
        from app.database import get_db_connection

        import datetime as _dt

        today_utc = _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%d")
        conn = get_db_connection(settings.database_url)
        try:
            row = conn.execute(
                "SELECT COUNT(*) FROM sms_log WHERE direction='outbound' "
                "AND to_number=? AND date(created_at)=? AND status NOT IN ('suppressed','failed')",
                (to, today_utc),
            ).fetchone()
            count = row[0] if row else 0
        finally:
            conn.close()
        if count >= 2:
            log.info("Owner SMS rate limit: %d sent today to %s, blocking", count, to)
            return ActionResult(
                action="send_sms",
                success=False,
                detail=(
                    f"Owner SMS rate limit reached ({count}/day). "
                    "The owner has complained about too many texts. "
                    "Handle this autonomously or log it for the next VS Code session."
                ),
                data={"to": to, "rate_limited": True, "sent_today": count},
            )
    except Exception:
        pass

    # ── Safety gate: external SMS requires approval unless explicitly enabled ──
    try:
        unsafe_ok = bool(getattr(settings, "unsafe_actions_enabled", True))
        require_approval = bool(
            getattr(settings, "sms_send_external_requires_approval", True)
        )
        try:
            from app.services.owner_notifications import is_owner_number

            is_owner = is_owner_number(settings, to)
        except Exception:
            owner = str(getattr(settings, "owner_phone_number", "") or "").strip()
            is_owner = bool(owner and to == owner)
        if (not unsafe_ok) and require_approval and (not is_owner):
            tid = _create_approval_task(
                settings=settings,
                title=f"APPROVAL: Send SMS to {to}",
                description=(
                    "Requested SMS was blocked by safety settings.\n\n"
                    f"To: {to}\n\n"
                    f"Body:\n{body}"
                ),
                tags=["approval", "sms"],
            )
            detail = "Approval required (queued as task)"
            if tid:
                detail += f" — task #{tid}"
            return ActionResult(
                action="send_sms",
                success=False,
                detail=detail,
                data={
                    "to": to,
                    "approval_task_id": tid,
                },
            )
    except Exception:
        pass

    from app.sms_service import send_message

    result = send_message(settings=settings, to=to, body=body)

    # Log to sms_log for audit trail - ONLY when the service layer did not.
        # ONE SEND, ONE ROW. `send_message` is wrapped by `_audited_send`, which
        # already wrote this attempt to sms_log and set `_audit_logged`. Writing again
        # here put two rows in the table for the same sid, double-counted every message
        # against the owner's daily quota, and recorded a relay SUPPRESSION as
        # status="failed" - two different facts reported as one. See main.py:6139.
    try:
        from app.database import log_sms

        if not (result or {}).get("_audit_logged"):
            log_sms(
                db_url=settings.database_url,
                twilio_sid=result.get("sid") if result.get("ok") else None,
                direction="outbound",
                from_number=str(getattr(settings, "twilio_phone_number", "") or ""),
                to_number=to,
                body=body,
                status=(result.get("status")
                        or ("sent" if result.get("ok") else "failed")),
                error_message=result.get("error") if not result.get("ok") else None,
                agent_id="orchestrator",
            )
    except Exception:
        pass

    if result.get("ok"):
        log.info("Action send_sms: sent to %s (%d chars)", to, len(body))
        return ActionResult(
            action="send_sms",
            success=True,
            detail=f"Sent to {to}",
            data={"to": to, "sid": result.get("sid"), "body": body},
        )
    else:
        error = result.get("error", "Unknown error")
        log.warning("Action send_sms failed: %s", error)
        return ActionResult(
            action="send_sms",
            success=False,
            detail=error,
            data={"to": to},
        )


# ─── Long-Running Task & Repo Management Executors ────────────


# ─── GitHub & Repository Actions ─────────────────────────────


# ---------------------------------------------------------------------------
# Contact actions
# ---------------------------------------------------------------------------


def _exec_contact_search(
    params: dict[str, str],
    *,
    settings: Any = None,
) -> ActionResult:
    """Search contacts by name, phone, or email."""
    query = (params.get("query") or "").strip()
    limit = int(params.get("limit") or "20")
    if not query:
        return ActionResult(
            action="contact_search",
            success=False,
            detail='Missing "query" parameter',
        )
    try:
        from app.database import list_contacts

        results = list_contacts(
            settings.database_url,
            query=query,
            limit=limit,
        )
        if not results:
            return ActionResult(
                action="contact_search",
                success=True,
                detail=f"No contacts matching '{query}'",
                data={"contacts": [], "count": 0},
            )
        summary_lines = []
        for c in results[:20]:
            line = f"- {c['name']}"
            if c.get("phone"):
                line += f" ({c['phone']})"
            if c.get("company"):
                line += f" @ {c['company']}"
            if c.get("relationship"):
                line += f" [{c['relationship']}]"
            summary_lines.append(line)
        return ActionResult(
            action="contact_search",
            success=True,
            detail=(f"{len(results)} contact(s) found:\n" + "\n".join(summary_lines)),
            data={
                "contacts": results,
                "count": len(results),
            },
        )
    except Exception as exc:
        return ActionResult(
            action="contact_search",
            success=False,
            detail=f"Search failed: {exc}",
        )


def _exec_contact_lookup(
    params: dict[str, str],
    *,
    settings: Any = None,
) -> ActionResult:
    """Look up a specific contact by phone number or ID."""
    key = (params.get("phone_or_id") or "").strip()
    if not key:
        return ActionResult(
            action="contact_lookup",
            success=False,
            detail='Missing "phone_or_id" parameter',
        )
    try:
        contact = None
        # Try numeric ID first
        if key.isdigit():
            from app.database import get_contact_by_id

            contact = get_contact_by_id(
                settings.database_url,
                int(key),
            )
        # Fall back to phone lookup
        if not contact:
            from app.database import get_contact_by_phone

            contact = get_contact_by_phone(
                settings.database_url,
                key,
            )

        if not contact:
            return ActionResult(
                action="contact_lookup",
                success=True,
                detail=f"No contact found for '{key}'",
                data={"contact": None},
            )

        # Include recent interactions
        from app.database import list_contact_interactions

        interactions = list_contact_interactions(
            settings.database_url,
            contact["id"],
            limit=5,
        )
        contact["recent_interactions"] = interactions

        detail = f"{contact['name']}"
        if contact.get("phone"):
            detail += f" | {contact['phone']}"
        if contact.get("email"):
            detail += f" | {contact['email']}"
        if contact.get("company"):
            detail += f" @ {contact['company']}"
        if contact.get("interaction_count"):
            detail += f" | {contact['interaction_count']} interactions"

        return ActionResult(
            action="contact_lookup",
            success=True,
            detail=detail,
            data={"contact": contact},
        )
    except Exception as exc:
        return ActionResult(
            action="contact_lookup",
            success=False,
            detail=f"Lookup failed: {exc}",
        )


def _exec_contact_update(
    params: dict[str, str],
    *,
    settings: Any = None,
) -> ActionResult:
    """Update a contact's profile fields."""
    contact_id = params.get("id") or ""
    if not contact_id or not contact_id.strip().isdigit():
        return ActionResult(
            action="contact_update",
            success=False,
            detail='Missing or invalid "id" parameter',
        )
    cid = int(contact_id.strip())

    # Collect updatable fields
    kwargs: dict[str, Any] = {}
    for fld in (
        "name",
        "phone",
        "email",
        "address",
        "company",
        "role",
        "notes",
        "relationship",
    ):
        val = params.get(fld)
        if val is not None:
            kwargs[fld] = val

    tags_raw = params.get("tags")
    if tags_raw is not None:
        import json as _json

        try:
            kwargs["tags"] = _json.loads(tags_raw)
        except Exception:
            kwargs["tags"] = [t.strip() for t in tags_raw.split(",") if t.strip()]

    fav = params.get("favorite")
    if fav is not None:
        kwargs["favorite"] = _to_bool(fav)

    if not kwargs:
        return ActionResult(
            action="contact_update",
            success=False,
            detail="No fields to update",
        )

    try:
        from app.database import update_contact

        ok = update_contact(
            settings.database_url,
            cid,
            **kwargs,
        )
        if ok:
            return ActionResult(
                action="contact_update",
                success=True,
                detail=(
                    f"Contact {cid} updated: "
                    + ", ".join(f"{k}={v}" for k, v in kwargs.items())
                ),
                data={"contact_id": cid, "updated": kwargs},
            )
        return ActionResult(
            action="contact_update",
            success=False,
            detail=f"Contact {cid} not found",
        )
    except Exception as exc:
        return ActionResult(
            action="contact_update",
            success=False,
            detail=f"Update failed: {exc}",
        )


# ── Workflow / Goal exec functions ────────────────────────────────


def _exec_create_goal(
    params: dict[str, Any],
    *,
    settings: Any = None,
    agent_id: str = "orchestrator",
) -> ActionResult:
    """Create a multi-step goal with ordered steps."""
    import json as _json

    from app.services.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    title = (params.get("title") or "").strip()
    if not title:
        return ActionResult(
            action="create_goal",
            success=False,
            detail="title is required",
        )

    objective = (params.get("objective") or "").strip()
    steps_raw = params.get("steps", [])
    if isinstance(steps_raw, str):
        try:
            steps_raw = _json.loads(steps_raw)
        except _json.JSONDecodeError:
            return ActionResult(
                action="create_goal",
                success=False,
                detail="steps must be valid JSON array",
            )

    if not steps_raw or not isinstance(steps_raw, list):
        return ActionResult(
            action="create_goal",
            success=False,
            detail="at least one step is required (steps=[{title, description?, agent?}])",
        )

    priority = int(params.get("priority", 50))
    assigned = (params.get("assigned_agent") or agent_id).strip()
    deadline = params.get("deadline")

    try:
        goal_id = engine.create_goal(
            title=title,
            objective=objective,
            steps=steps_raw,
            priority=priority,
            assigned_agent=assigned,
            deadline=deadline,
            source="ceo_action",
        )
        return ActionResult(
            action="create_goal",
            success=True,
            detail=(
                f"Created goal '{title}' ({goal_id}) " f"with {len(steps_raw)} steps"
            ),
            data={"goal_id": goal_id, "steps": len(steps_raw)},
        )
    except Exception as exc:
        return ActionResult(
            action="create_goal",
            success=False,
            detail=f"Failed to create goal: {exc}",
        )


def _exec_complete_goal_step(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Mark a goal step as completed and advance the goal."""
    import json as _json

    from app.services.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    resolved_goal_id = ""
    resolved_step_number: int | None = None

    step_id_raw = (params.get("step_id") or "").strip()
    if step_id_raw:
        try:
            step_row = (
                engine._conn()
                .execute(
                    "SELECT goal_id, step_number FROM goal_steps WHERE id = ?",
                    (int(step_id_raw),),
                )
                .fetchone()
            )
        except (TypeError, ValueError):
            step_row = None
        if step_row:
            resolved_goal_id = str(step_row["goal_id"] or "").strip()
            resolved_step_number = int(step_row["step_number"])

    goal_id = (params.get("goal_id") or "").strip()
    if resolved_goal_id:
        goal_id = resolved_goal_id
    if not goal_id:
        return ActionResult(
            action="complete_goal_step",
            success=False,
            detail="goal_id is required",
        )

    try:
        step_number = int(params.get("step_number", -1))
    except (ValueError, TypeError):
        if resolved_step_number is None:
            return ActionResult(
                action="complete_goal_step",
                success=False,
                detail="step_number must be an integer",
            )
        step_number = resolved_step_number

    if step_number < 0:
        if resolved_step_number is None:
            return ActionResult(
                action="complete_goal_step",
                success=False,
                detail="step_number is required (0-indexed)",
            )
        step_number = resolved_step_number

    output_raw = params.get("output", {})
    if isinstance(output_raw, str):
        try:
            output_raw = _json.loads(output_raw)
        except _json.JSONDecodeError:
            output_raw = {"result": output_raw}

    try:
        engine.start_step(goal_id, step_number)
        engine.complete_step(goal_id, step_number, output_raw)

        # Check what's next
        next_step = engine.get_next_step(goal_id)
        if next_step:
            return ActionResult(
                action="complete_goal_step",
                success=True,
                detail=(
                    f"Completed step {step_number} of goal {goal_id}. "
                    f"Next: step {next_step.step_number} "
                    f"'{next_step.step_title}' "
                    f"(assigned to {next_step.assigned_agent})"
                ),
                data={
                    "goal_id": goal_id,
                    "completed_step": step_number,
                    "next_step": next_step.step_number,
                    "next_title": next_step.step_title,
                    "next_agent": next_step.assigned_agent,
                },
            )
        else:
            return ActionResult(
                action="complete_goal_step",
                success=True,
                detail=(
                    f"Completed step {step_number} of goal {goal_id}. "
                    f"Goal is now complete!"
                ),
                data={
                    "goal_id": goal_id,
                    "completed_step": step_number,
                    "goal_complete": True,
                },
            )
    except Exception as exc:
        return ActionResult(
            action="complete_goal_step",
            success=False,
            detail=f"Failed to complete step: {exc}",
        )


def _exec_pause_goal(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Pause an active goal."""
    from app.services.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    goal_id = (params.get("goal_id") or "").strip()
    if not goal_id:
        return ActionResult(
            action="pause_goal",
            success=False,
            detail="goal_id is required",
        )

    try:
        engine.pause_goal(goal_id)
        return ActionResult(
            action="pause_goal",
            success=True,
            detail=f"Paused goal {goal_id}",
            data={"goal_id": goal_id, "status": "paused"},
        )
    except Exception as exc:
        return ActionResult(
            action="pause_goal",
            success=False,
            detail=f"Failed to pause goal: {exc}",
        )


def _exec_cancel_goal(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Cancel a goal and all its pending steps."""
    from app.services.workflow_engine import get_workflow_engine

    engine = get_workflow_engine()
    goal_id = (params.get("goal_id") or "").strip()
    if not goal_id:
        return ActionResult(
            action="cancel_goal",
            success=False,
            detail="goal_id is required",
        )

    try:
        engine.cancel_goal(goal_id)
        return ActionResult(
            action="cancel_goal",
            success=True,
            detail=f"Cancelled goal {goal_id}",
            data={"goal_id": goal_id, "status": "cancelled"},
        )
    except Exception as exc:
        return ActionResult(
            action="cancel_goal",
            success=False,
            detail=f"Failed to cancel goal: {exc}",
        )


# ── Owner VS Code activity ─────────────────────────────────────────────


def _exec_owner_vscode_activity(
    params: dict[str, str],
) -> ActionResult:
    """Return a summary of the owner's recent VS Code Copilot chats.

    Gives the secretary visibility into what the owner is actively
    working on across all VS Code windows and repositories.
    """
    days = 7
    raw_days = (params.get("days") or "").strip()
    if raw_days:
        try:
            days = max(1, min(int(raw_days), 30))
        except ValueError:
            pass
    workspace = (params.get("workspace") or "").strip() or None

    try:
        from scripts.vscode_chat_extractor import extract_all_sessions

        data = extract_all_sessions(
            days=days,
            workspace_filter=workspace,
        )
    except Exception as exc:
        return ActionResult(
            action="owner_vscode_activity",
            success=False,
            detail=f"Failed to extract VS Code chats: {exc}",
        )

    summary = data.get("summary", {})
    by_ws = summary.get("by_workspace", {})

    # Build concise text summary for the LLM
    lines = [
        f"Owner VS Code activity (last {days} days): "
        f"{summary.get('total_sessions', 0)} sessions, "
        f"{summary.get('total_user_messages', 0)} messages "
        f"across {summary.get('workspaces_active', 0)} workspaces.",
        "",
    ]
    for ws_name, ws_data in sorted(by_ws.items(), key=lambda x: -x[1]["session_count"]):
        last = (
            ws_data.get("last_active", "")[:16] if ws_data.get("last_active") else "?"
        )
        lines.append(
            f"  {ws_name}: {ws_data['session_count']} sessions, "
            f"{ws_data['user_message_count']} msgs, last: {last}"
        )

    lines.append("")
    lines.append("Recent topics:")
    for t in summary.get("recent_topics", [])[:15]:
        lines.append(f"  [{t['workspace']}] {t['title']}")

    # Include recent user messages for context
    lines.append("")
    lines.append("Recent user messages (newest first):")
    for s in data.get("sessions", [])[:10]:
        ws = s.get("workspace", "?")
        for msg in s.get("user_messages", [])[:2]:
            short = msg[:120].replace("\n", " ")
            lines.append(f"  [{ws}] {short}")

    return ActionResult(
        action="owner_vscode_activity",
        success=True,
        detail="\n".join(lines),
        data={
            "summary": summary,
            "session_count": summary.get("total_sessions", 0),
            "workspaces_active": summary.get("workspaces_active", 0),
        },
    )


# ── Bulk company hygiene exec functions ────────────────────────────


def _exec_bulk_cancel_failed_goals(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Cancel all failed goals in one pass (no per-goal LLM cost)."""
    from app.services.bulk_cleanup import bulk_cancel_failed_goals

    db_url = getattr(settings, "database_url", "data/secretary.db")
    try:
        older = float(params.get("older_than_hours") or 0)
    except (TypeError, ValueError):
        older = 0
    dry_run = str(params.get("dry_run", "")).lower() in ("1", "true", "yes")
    result = bulk_cancel_failed_goals(
        db_url,
        older_than_hours=older,
        dry_run=dry_run,
    )
    detail = (
        f"Bulk cancel failed goals: found {result['failed_total']}, "
        f"cancelled {result['cancelled']}, steps skipped "
        f"{result['steps_skipped']}, approvals expired "
        f"{result['approvals_expired']}"
        + (" (DRY RUN - no changes made)" if dry_run else "")
    )
    return ActionResult(
        action="bulk_cancel_failed_goals",
        success=True,
        detail=detail,
        data=result,
    )


def _exec_bulk_prune_idle_agents(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Deactivate agents with zero active work (idle roster shrink)."""
    from app.services.bulk_cleanup import bulk_prune_idle_agents

    dry_run = str(params.get("dry_run", "")).lower() in ("1", "true", "yes")
    try:
        min_idle_days = float(params.get("min_idle_days") or 7)
    except (TypeError, ValueError):
        min_idle_days = 7
    result = bulk_prune_idle_agents(
        dry_run=dry_run,
        min_idle_days=min_idle_days,
    )
    detail = (
        f"Prune idle agents: scanned {result['agents_scanned']}, "
        f"prunable {result['prunable_found']}, deactivated "
        f"{result['pruned']}"
        + (" (DRY RUN - no changes made)" if dry_run else "")
    )
    return ActionResult(
        action="bulk_prune_idle_agents",
        success=True,
        detail=detail,
        data=result,
    )


def _exec_bulk_close_duplicate_tasks(
    params: dict[str, Any],
    *,
    settings: Any = None,
) -> ActionResult:
    """Close duplicate open-task clusters, keeping the oldest canonical."""
    from app.services.bulk_cleanup import bulk_close_duplicate_tasks

    db_url = getattr(settings, "database_url", "data/secretary.db")
    dry_run = str(params.get("dry_run", "")).lower() in ("1", "true", "yes")
    try:
        min_overlap = float(params.get("min_overlap") or 0.4)
    except (TypeError, ValueError):
        min_overlap = 0.4
    result = bulk_close_duplicate_tasks(
        db_url,
        dry_run=dry_run,
        min_overlap=min_overlap,
    )
    detail = (
        f"Bulk close duplicate tasks: scanned {result['active_tasks_scanned']}, "
        f"clusters {result['clusters_found']}, closed {result['closed']}, "
        f"kept {result['kept']}"
        + (" (DRY RUN - no changes made)" if dry_run else "")
    )
    return ActionResult(
        action="bulk_close_duplicate_tasks",
        success=True,
        detail=detail,
        data=result,
    )

