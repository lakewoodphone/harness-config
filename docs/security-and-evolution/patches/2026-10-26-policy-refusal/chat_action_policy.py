"""Shared normalization and policy helpers for chat action execution."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Callable

from app.chat_action_parsing import ActionResult

# Common LLM parameter mistakes -> correct names.
# Applied before dispatch so agents learn correct names from
# error messages but their intent still executes.
PARAM_ALIASES: dict[str, dict[str, str]] = {
    "schedule_notification": {
        "datetime": "scheduled_time",
        "when": "scheduled_time",
        "time": "scheduled_time",
        "remind_at": "scheduled_time",
        "minutes_from_now": "scheduled_time",
        "to": "recipient",
        "phone": "recipient",
        "type": "notif_type",
    },
    "schedule_reminder": {
        "datetime": "remind_at",
        "when": "remind_at",
        "time": "remind_at",
        "scheduled_time": "remind_at",
        "to": "recipient",
    },
    "update_task": {
        "task_id": "id",
    },
    "assign_task": {
        "task_id": "id",
        "assignee": "assigned_to",
        "department": "assigned_to",
        "agent": "assigned_to",
        "agent_id": "assigned_to",
    },
    "close_task": {
        "task_id": "id",
    },
    "create_task": {
        "assigned_to": "assigned_to",
        "assignee": "assigned_to",
        "department": "assigned_to",
        "mission": "mission_id",
        "okr": "mission_id",
        "objective_id": "mission_id",
    },
    "link_task_to_mission": {
        "task_id": "id",
        "mission": "mission_id",
        "okr": "mission_id",
        "objective": "mission_id",
    },
    "send_sms": {
        "phone": "to",
        "number": "to",
        "message": "body",
        "text": "body",
    },
    "repo_read_file": {
        "repo": "repo_path",
        "repo_name": "repo_path",
        "repository": "repo_path",
        "repo_alias": "repo_path",
        "file": "path",
        "file_path": "path",
        "filepath": "path",
        "filename": "path",
    },
    "repo_list_dir": {
        "repo": "repo_path",
        "repo_name": "repo_path",
        "repository": "repo_path",
        "repo_alias": "repo_path",
        "dir": "path",
        "dir_path": "path",
        "directory": "path",
        "folder": "path",
    },
    "repo_map": {
        "repo": "repo_path",
        "repo_name": "repo_path",
        "repository": "repo_path",
        "repo_alias": "repo_path",
    },
    "repo_search": {
        "repo": "repo_path",
        "repo_name": "repo_path",
        "repository": "repo_path",
        "repo_alias": "repo_path",
        "search": "query",
        "text": "query",
    },
    "repo_run_command": {
        "repo": "repo_path",
        "repo_name": "repo_path",
        "repository": "repo_path",
        "repo_alias": "repo_path",
        "cmd": "command",
        "shell_command": "command",
    },
    "hire_department": {
        "department": "name",
        "department_name": "name",
        "dept": "name",
        "dept_name": "name",
        "title": "name",
        "focus": "focus_areas",
        "focusareas": "focus_areas",
    },
    "fire_agent": {
        "agent": "agent_id",
        "id": "agent_id",
        "department": "agent_id",
        "dept": "agent_id",
    },
    "reactivate_agent": {
        "agent": "agent_id",
        "id": "agent_id",
        "department": "agent_id",
        "dept": "agent_id",
        "name": "agent_id",
    },
    "import_skill": {
        "url": "source",
        "source_url": "source",
        "skill_url": "source",
        "confirm": "confirm_remote",
        "confirmremote": "confirm_remote",
        "tool": "tool_name",
    },
    "build_tool": {
        "spec": "specification",
        "tool_spec": "specification",
        "code": "specification",
        "desc": "description",
        "tool_name": "name",
        "tool": "name",
    },
    "upgrade_tool": {
        "tool_name": "name",
        "tool": "name",
        "issue": "feedback",
        "fix": "feedback",
        "improvement": "feedback",
        "changes": "feedback",
    },
    "delete_tool": {
        "tool_name": "name",
        "tool": "name",
        "remove": "permanent",
        "hard_delete": "permanent",
    },
    "list_dynamic_tools": {
        "filter": "status",
        "show": "status",
    },
    "calendar_create": {
        "title": "summary",
        "name": "summary",
        "event": "summary",
        "date": "start",
        "when": "start",
        "time": "start",
        "where": "location",
        "place": "location",
        "notes": "description",
        "body": "description",
        "guests": "attendees",
        "invite": "attendees",
    },
    "calendar_update": {
        "id": "event_id",
        "title": "summary",
        "name": "summary",
        "date": "start",
        "when": "start",
        "where": "location",
        "notes": "description",
    },
    "calendar_delete": {
        "id": "event_id",
    },
    "calendar_get": {
        "id": "event_id",
    },
    "calendar_list": {
        "search": "query",
        "filter": "query",
        "count": "max_results",
        "limit": "max_results",
    },
    "gmail_list": {
        "count": "max_results",
        "limit": "max_results",
        "email": "account",
        "from_account": "account",
    },
    "gmail_read": {
        "id": "message_id",
        "msg_id": "message_id",
        "email": "account",
    },
    "gmail_search": {
        "search": "query",
        "filter": "query",
        "text": "query",
        "count": "max_results",
        "limit": "max_results",
        "email": "account",
    },
    "gmail_send": {
        "recipient": "to",
        "email": "to",
        "title": "subject",
        "message": "body",
        "text": "body",
        "content": "body",
        "from": "account",
        "from_account": "account",
    },
    "gmail_draft": {
        "recipient": "to",
        "email": "to",
        "title": "subject",
        "message": "body",
        "text": "body",
        "content": "body",
        "from": "account",
        "from_account": "account",
    },
    "qb_search": {
        "from": "start_date",
        "to": "end_date",
        "since": "start_date",
        "until": "end_date",
        "vendor": "description",
        "name": "description",
        "text": "description",
    },
    "qb_vendors": {
        "name": "search",
        "filter": "search",
        "query": "search",
    },
    "ha_states": {
        "type": "domain",
        "filter": "domain",
        "count": "limit",
    },
    "ha_entity": {
        "entity": "entity_id",
        "id": "entity_id",
    },
    "ha_call_service": {
        "type": "domain",
        "action": "service",
        "entity": "entity_id",
        "id": "entity_id",
    },
    "ha_doors": {
        "door": "buzz_in",
        "unlock": "buzz_in",
        "open": "buzz_in",
    },
    "memory_search": {
        "q": "query",
        "text": "query",
        "search": "query",
        "count": "n_results",
        "limit": "n_results",
        "type": "category",
    },
    "memory_save": {
        "text": "content",
        "memory": "content",
        "type": "category",
    },
    "browser_goto": {
        "page": "url",
        "link": "url",
        "site": "url",
        "website": "url",
    },
    "browser_click": {
        "element": "selector",
        "target": "selector",
        "css": "selector",
    },
    "browser_fill": {
        "value": "text",
        "input": "text",
        "element": "selector",
        "target": "selector",
        "css": "selector",
    },
    "browser_screenshot": {
        "page": "url",
        "site": "url",
    },
    "browser_run": {
        "steps": "actions",
        "script": "actions",
        "page": "url",
        "site": "url",
    },
    "browser_act": {
        "task": "goal",
        "objective": "goal",
        "instruction": "goal",
        "page": "url",
        "site": "url",
        "start": "url",
    },
    "browser_save_session": {
        "session": "name",
        "service": "name",
        "page": "url",
        "site": "url",
    },
    "ask_owner": {
        "message": "question",
        "text": "question",
        "body": "question",
        "reason": "context",
        "detail": "context",
        "details": "context",
        "priority": "urgency",
        "level": "urgency",
    },
    "propose_owner_assumption": {
        "pref": "key",
        "preference": "key",
        "fact": "key",
        "field": "key",
        "val": "value",
        "guess": "value",
        "confidence": "confidence",
        "conf": "confidence",
        "evidence": "evidence",
        "why": "evidence",
        "because": "evidence",
    },
    "propose_spend_request": {
        "name": "title",
        "subject": "title",
        "desc": "description",
        "details": "description",
        "reason": "description",
        "amount": "amount_usd",
        "cost": "amount_usd",
        "price": "amount_usd",
        "usd": "amount_usd",
        "vendor": "vendor",
        "payee": "vendor",
    },
    "propose_human_job": {
        "name": "title",
        "role": "title",
        "desc": "description",
        "details": "description",
        "platform": "platform",
        "budget": "budget_usd",
        "amount": "budget_usd",
        "usd": "budget_usd",
        "post": "job_post_text",
        "job_post": "job_post_text",
        "job": "job_post_text",
        "text": "job_post_text",
    },
    "propose_mission": {
        "name": "title",
        "goal": "title",
        "objective": "title",
        "mission": "title",
        "desc": "description",
        "results": "key_results",
        "krs": "key_results",
        "period": "timeframe",
        "duration": "timeframe",
    },
    "update_mission": {
        "mission_id": "id",
        "progress_pct": "progress",
    },
    "list_missions": {
        "filter": "status",
        "show": "status",
    },
    "contact_search": {
        "name": "query",
        "phone": "query",
        "email": "query",
        "text": "query",
        "search": "query",
        "count": "limit",
    },
    "contact_lookup": {
        "phone": "phone_or_id",
        "number": "phone_or_id",
        "id": "phone_or_id",
        "contact_id": "phone_or_id",
    },
    "contact_update": {
        "contact_id": "id",
    },
    "web_search": {
        "search_query": "query",
        "search": "query",
        "q": "query",
        "text": "query",
        "term": "query",
        "keywords": "query",
    },
    "fetch_url": {
        "link": "url",
        "page": "url",
        "site": "url",
        "website": "url",
        "href": "url",
        "address": "url",
    },
    "deep_research": {
        "path": "directive_path",
        "file": "directive_path",
        "directive": "directive_path",
        "output": "output_path",
    },
    "save_memory": {
        "text": "content",
        "memory": "content",
        "note": "content",
        "type": "category",
        "tag": "category",
    },
    "system_health": {},
    "start_work_session": {
        "task": "task_id",
        "desc": "description",
        "details": "description",
        "goal": "description",
    },
    "enqueue_job": {
        "desc": "description",
        "details": "description",
        "task": "title",
        "name": "title",
    },
}


def _to_bool(value: str | None, *, default: bool = False) -> bool:
    v = str(value or "").strip().lower()
    if not v:
        return bool(default)
    return v in {"1", "true", "yes", "y", "on"}


def _normalize_params(
    action_name: str,
    params: dict[str, str],
) -> dict[str, str]:
    """Apply param name aliases so common LLM mistakes still work."""
    aliases = PARAM_ALIASES.get(action_name)
    if not aliases:
        return params
    normalized = dict(params)
    for wrong_name, correct_name in aliases.items():
        if wrong_name in normalized and correct_name not in normalized:
            normalized[correct_name] = normalized.pop(wrong_name)
    return normalized


def _policy_params_preview(
    action_params: dict[str, str],
    *,
    max_value_chars: int = 300,
) -> dict[str, str]:
    preview: dict[str, str] = {}
    for key, value in action_params.items():
        if key == "_action":
            continue
        text = str(value)
        if len(text) <= max_value_chars:
            preview[key] = text
        else:
            preview[key] = f"{text[:max_value_chars]}..."
    return preview


def _enforce_action_policy(
    action_name: str,
    action_params: dict[str, str],
    *,
    settings: Any,
    agent_id: str = "",
    create_approval_task: Callable[..., int | None],
) -> ActionResult | None:
    from app.policy import get_policy_enforcer

    decision = get_policy_enforcer().check_and_log(
        action_name,
        action_params,
        settings=settings,
        agent_id=agent_id,
    )
    if decision.allowed:
        return None

    data: dict[str, Any] = {
        "policy_denied": True,
        # The same marker the autonomy gate sets: this action never ran, so it did
        # not fail. `chat_action_runtime._is_policy_refusal` is the one reader, and
        # it is what keeps a deliberate denial out of the retry loop, the action
        # circuit breaker and the tool-loop strike counter.
        "policy_refused": True,
        "policy_refusal_kind": "deterministic_policy",
        "policy_reason": decision.reason,
    }
    if decision.tier is not None:
        data["policy_tier"] = decision.tier.value

    detail = f"Policy denied: {decision.reason}"
    if decision.requires_approval:
        params_preview = _policy_params_preview(action_params)
        # Exact dedupe key per (action, agent, resource): `create_task`'s default
        # fuzzy title match ignores the parameters, so two different requests would
        # share one approval task and the owner would approve something he was never
        # shown. `dedupe_key` is indexed on `tasks` and checked before the fuzzy path.
        resource_digest = hashlib.sha256(
            json.dumps(
                {
                    str(k): str(v)
                    for k, v in (action_params or {}).items()
                    if str(k) != "_action"
                },
                sort_keys=True,
                default=str,
            ).encode("utf-8")
        ).hexdigest()[:12]
        task_id = create_approval_task(
            settings=settings,
            title=f"APPROVAL: {action_name}",
            description=(
                "Requested action was blocked by deterministic policy. Nothing ran; "
                "this is a policy refusal, not a failure.\n\n"
                f"Action: {action_name}\n"
                f"Reason: {decision.reason}\n\n"
                f"Parameters:\n{json.dumps(params_preview, indent=2)}"
            ),
            tags=["approval", "policy", action_name],
            dedupe_key=(
                f"policy-refusal:policy:{action_name}:"
                f"{agent_id or '-'}:{resource_digest}"
            ),
        )
        data["approval_task_id"] = task_id
        detail = "Policy denied: requires owner approval"
        if task_id:
            detail += f" — task #{task_id}"
        detail += " (a policy refusal, not a failure: nothing ran and repeating it cannot change the answer)"

    return ActionResult(
        action=action_name,
        success=False,
        detail=detail,
        data=data,
    )


def _record_policy_success(
    action_name: str,
    action_params: dict[str, str],
) -> None:
    from app.policy import get_policy_enforcer

    get_policy_enforcer().record_success(
        action_name,
        action_params,
    )


__all__ = [
    "PARAM_ALIASES",
    "_enforce_action_policy",
    "_normalize_params",
    "_policy_params_preview",
    "_record_policy_success",
    "_to_bool",
]
