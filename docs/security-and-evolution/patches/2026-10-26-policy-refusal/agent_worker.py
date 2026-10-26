"""Productive agent tick — claim→execute→report work loop.

Replaces the reflection-heavy agent tick with a focused execution cycle:
1. Claim the highest-priority pending step
2. Build minimal LLM context with department-specific tools
3. Make multi-turn LLM calls with structured tool calling (max 3 rounds)
4. Gate each tool call through autonomy framework (L0-L4)
5. Execute real actions via chat_actions dispatcher
6. Record outcomes for feedback (autonomy, metrics, memory)

Directive 008: Autonomous Work Generation & Department Activation.
Directive 009: Department Tool Execution & Closed-Loop Autonomy.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

# Transient SQLite write-lock resilience: agent ticks share the DB with HTTP
# handlers; under load a commit can hit "database is locked". commit_retry()
# waits through the busy window and retries before giving up. Local alias so
# call sites read cleanly without a wide refactor.
from app.database import commit_retry as _commit_retry

def _commit(conn):
    _commit_retry(conn)


log = logging.getLogger(__name__)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_iso_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


# Budget cap per agent per day (7 agents, $5/day total ≈ $0.71 each)
DAILY_BUDGET_PER_AGENT = 1.20

# Stale claim timeout in minutes
STALE_CLAIM_MINUTES = 30

# Cooldown before a released/blocked step can be claimed again. Prevents
# the agent from re-claiming the same dead step (pre-flight skip, meta-only
# burn-out, exhausted retries) every tick while healthy work behind it
# starves. `reset_blocked_required_tool_steps` clears completed_at/attempts
# so legitimately recovered steps reopen immediately.
RELEASED_STEP_COOLDOWN_MINUTES = 30

# Multi-turn limits
MAX_TOOL_ROUNDS = 5
MAX_OUTPUT_TOKENS = 1200
TOOL_RESULT_TRUNCATE = 12000

# Preferred models for department agents.
#
# STANDING RULE (owner, 2026-09-15, verbatim: "ai models change very often, can
# never be hardcoded and get changed and updated all the time so we need robust
# easy flows for that"): a model id is resolved at RUNTIME from the gateway's
# own catalogue, route aliases are preferred, every configured id is validated
# against that catalogue and dropped when it is not listed, the result is cached
# with single-flight, and resolution fails soft -- never silently.
#
# What this replaces (measured 2026-10-01 on the authority): the list was the
# single hardcoded literal `deepseek-v4-flash`, and `_available_department_models`
# fell back to raw `model_registry` rows. That produced a chain whose FIRST
# entry was the ceo-tier `deepinfra/deepseek-ai/DeepSeek-V4-Pro-0813` for every
# department, which is not in `COPILOT_MODELS`, so every department burned a
# round on "not in COPILOT roster" and then handed the gateway an alias anyway.
# The registry chain is now only a last resort, and it is catalogue-validated.
#
# Route aliases first: an alias is the one id whose whole purpose is to be
# re-pointed at a live model without a code change, which is exactly what the
# standing rule asks for.
DEPT_MODEL_CANDIDATES = (
    "secretary-fast",
    "secretary-auto",
    "secretary-smart",
)

#: The aliases this module may pin a department to. `secretary-genius` is
#: deliberately absent: measured 502 on 2026-09-15, and the alarm rule is
#: "prefer the route aliases ... never `secretary-genius`".
DEPT_ROUTE_ALIASES = ("secretary-fast", "secretary-auto", "secretary-smart")

#: Operator override, per tier, comma-separated, highest precedence first.
#: An operator swaps a department's model by setting an env var, not by editing
#: code -- and an id that is not in the live catalogue is DROPPED with a
#: warning, so a typo cannot silently pin a dead route again.
DEPT_MODEL_ENV_CHAIN = (
    "SECRETARY_DEPT_MODEL",
    "SECRETARY_DEPT_MODELS",
    "SECRETARY_AGENT_MODEL_CHAIN",
)

#: How long a resolved chain is trusted before the catalogue is consulted again.
DEPT_MODEL_CACHE_TTL_SEC = 300.0

_DEPT_MODEL_LOCK = threading.Lock()
_DEPT_MODEL_CACHE: dict[str, Any] = {
    "resolved_at": 0.0,
    "chain": (),
    "source": "unresolved",
    "error": "",
}

# Map short model names (as used by legacy config) to full canonical IDs that
# the AI gateway can resolve as direct provider pins (bypassing smart routing --
# see `_CAPABILITY_DB` in smart_router.py). Kept for callers that still hold a
# short id; a value here is NOT a configured model, only a translation table.
# Updated 2026-08-23: DeepInfra is the primary pipe for both flash and pro.
SHORT_TO_CANONICAL_MODEL: dict[str, str] = {
    "deepseek-v4-flash": "deepseek/deepseek-v4-flash",
    "deepseek-v4-pro": "deepseek/deepseek-v4-pro",
}

# Informational tools alone do not count as real work completion.
META_ONLY_TOOLS = frozenset(
    {
        "fetch_url",
        "memory_search",
        "save_memory",
        "schedule_reminder",
        "update_progress",
        "web_search",
    }
)

# FIX (2026-08-31): intent-aware meta tools. A meta tool IS the
# deliverable when the step description signals matching intent — e.g.
# a "research market trends" step's product is web_search/fetch_url
# output; a "set health reminders" step's product is schedule_reminder
# calls. Without this, _has_productive_tool_use falsely blocked real
# work (3 steps re-blocked on 2026-08-31 with 8-9 search calls each),
# starving otherwise-fine goals.
META_TOOL_INTENT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "web_search": (
        "research",
        "evaluate",
        "analyz",
        "investigat",
        "market trend",
        "landscape",
        "forecast",
        "sourc",
        "competitive",
        "industry trends",
        "look up",
        "find out",
    ),
    "fetch_url": (
        "research",
        "evaluate",
        "analyz",
        "investigat",
        "market trend",
        "landscape",
        "forecast",
        "sourc",
        "read",
        "article",
        "source",
    ),
    "schedule_reminder": (
        "remind",
        "reminder",
        "routine",
        "wellness",
        "health",
        "set reminders",
        "daily habits",
    ),
    "save_memory": (
        "remember",
        "save to memory",
        "store in memory",
        "note this",
        "record this",
    ),
    "memory_search": (
        "recall",
        "remember",
        "what did",
        "previous context",
    ),
    "update_progress": (
        "update progress",
        "report progress",
        "status update",
    ),
}

# A meta-only tick with a SUBSTANTIVE final response (>= this many chars)
# counts as productive — the LLM actually synthesized real output even
# though every tool it used was informational.
SUBSTANTIVE_RESPONSE_MIN_CHARS = 200

# Actions that represent real-world outputs (external-facing).
_REAL_OUTPUT_ACTIONS = frozenset(
    {
        "dialpad_send_sms",
        "send_sms",
        "gmail_send",
        "gmail_draft",
        "calendar_create",
        "calendar_update",
        "ha_call_service",
        "ha_doors",
        "ha_climate",
        "github_write_file",
        "github_create_issue",
        "github_create_pr",
    }
)

# Read-only / lookup tools that are always allowed through the
# REQUIRED TOOL gate.  Agents often need these to gather IDs or
# context before calling the required write tool.
_LOOKUP_TOOLS_ALWAYS_ALLOWED = frozenset(
    {
        "list_tasks",
        "system_health",
        "gmail_list",
        "gmail_read",
        "ha_status",
        "ha_climate",
        "web_search",
        "memory_search",
        "fetch_url",
        "github_list_issues",
        "github_read_file",
        "qb_snapshot",
        "qb_query",
        "qb_reconciliation",
        "ledger_status",
        "ledger_source_registry",
        "calendar_list",
        "repo_list_dir",
        "repo_search",
        "repo_read_file",
        "managed_workflow_status",
    }
)

# Per-action-per-step call limit to prevent runaway loops.
# If an action is called more than this many times in a single step, subsequent calls are
# blocked with an error message instead of executing.
#
# Two limits, because two kinds of tool. Measured 2026-09-20: `_PER_TICK_ACTION_LIMIT = 6` was one
# number for everything, and 146 of the 836 blocked tool calls in a 7-day window were this limit
# firing on `repo_search` - an agent reading a codebase, refused after its 7th search of a step and
# told to "spread remaining calls across future ticks", which it cannot do because the step is what
# it has run out of.
#
# A mutating tool called 11 times in a step is a runaway loop and must be blocked. A read-only
# lookup called 11 times is an agent doing research. The set used to make that distinction already
# exists - `_LOOKUP_TOOLS_ALWAYS_ALLOWED` - so this reuses it rather than declaring a second list
# that would drift away from it.
_PER_TICK_ACTION_LIMIT = 6
# Read-only / lookup tools get more room; they cannot mutate state, so the only cost of allowing
# them is tokens, and the limit is still finite.
_PER_TICK_LOOKUP_ACTION_LIMIT = 18

_ALLOWED_ROUTE_ALIASES = frozenset(
    {"secretary-fast", "secretary-auto", "secretary-smart"}
)
_ALLOWED_BUDGET_TIERS = frozenset(
    {"normal", "cost_aware", "economy", "survival"}
)


@dataclass(frozen=True)
class WorkerRouteContract:
    """Optional model/budget constraints embedded in a goal step."""

    public_alias: str = "secretary-auto"
    budget_tier: str = "cost_aware"
    task_type: str | None = None
    max_retries: int | None = None
    require_json_output: bool = False
    allow_copilot_fallback: bool | None = None
    allow_premium_fallback: bool = False


@dataclass(frozen=True)
class DepartmentCopilotFallbackPolicy:
    """Decision record for department fallback behavior."""

    allow_copilot: bool
    reason: str
    premium_allowed: bool = False


def _extract_route_contract(description: str) -> WorkerRouteContract:
    """Parse a compact ROUTE CONTRACT clause from task text."""
    import re

    if not description:
        return WorkerRouteContract()

    match = re.search(
        r"ROUTE\s+CONTRACT\s*:\s*(.+?)(?:\n\s*\n|$)",
        description,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return WorkerRouteContract()

    raw = match.group(1).strip()
    raw = raw.splitlines()[0].strip() if "\n" in raw else raw
    parts = [p.strip() for p in re.split(r";|,", raw) if p.strip()]
    values: dict[str, Any] = {}
    flags = " ".join(parts).lower()

    if "no copilot fallback" in flags or "block copilot fallback" in flags:
        values["allow_copilot_fallback"] = False
    elif "allow copilot fallback" in flags:
        values["allow_copilot_fallback"] = True

    if "allow premium fallback" in flags or "premium fallback allowed" in flags:
        values["allow_premium_fallback"] = True
    if re.search(r"\bjson\b", flags):
        values["require_json_output"] = True

    for part in parts:
        if "=" not in part:
            continue
        key, value = [x.strip().lower() for x in part.split("=", 1)]
        if key in {"alias", "model", "route"}:
            if value in _ALLOWED_ROUTE_ALIASES:
                values["public_alias"] = value
        elif key in {"budget", "budget_tier", "tier"}:
            normalized = value.replace("-", "_")
            if normalized in _ALLOWED_BUDGET_TIERS:
                values["budget_tier"] = normalized
        elif key in {"task", "task_type", "type"}:
            values["task_type"] = value[:80] or None
        elif key in {"retries", "max_retries"}:
            try:
                retries = int(value)
                if retries >= 0:
                    values["max_retries"] = min(retries, MAX_TOOL_ROUNDS)
            except ValueError:
                pass

    return WorkerRouteContract(**values)


def _department_copilot_fallback_policy(
    *,
    messages: list[dict[str, str]],
    agent_id: str,
    required_tools: list[str],
    has_tools: bool,
    contract: WorkerRouteContract | None = None,
) -> DepartmentCopilotFallbackPolicy:
    """Decide whether department work may fall back to Copilot/premium routes."""
    contract = contract or WorkerRouteContract()

    if contract.allow_copilot_fallback is False:
        return DepartmentCopilotFallbackPolicy(False, "contract_block", False)

    if contract.allow_copilot_fallback is True:
        return DepartmentCopilotFallbackPolicy(
            True,
            "contract_allow",
            contract.allow_premium_fallback,
        )

    if required_tools and has_tools:
        return DepartmentCopilotFallbackPolicy(
            True,
            "required_tool_continuity",
            False,
        )

    prompt_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if isinstance(message, dict)
    ).lower()
    if "critical" in prompt_text or agent_id in {"orchestrator", "dept_engineering"}:
        return DepartmentCopilotFallbackPolicy(
            True,
            "critical_or_engineering_continuity",
            False,
        )

    return DepartmentCopilotFallbackPolicy(False, "default_conserve_budget", False)


# ── Closed loop: the worker's doomed LLM call must have an exit ────────────
#
# The shape that caused the six-day August 2026 outage (3,246 ticks, zero
# completions, `/health` 200) is in this file: a dead model id on every
# candidate in the department chain, a gateway fallback that is refused
# (`default_conserve_budget`, :360 — `:357` before this block was inserted), and
# a tick loop that re-enters
# `_execute_llm_step` with rebuilt-but-identical inputs. Before this block
# nothing counted those failures and nothing changed state between them, so
# the loop had no exit at all. W6 gave the ROUTER the same exit
# (`smart_router.RouterDeadlock`, :1651-1817); this mirrors that shape at the
# worker site and records into the router's own outage ring so there is one
# surface, not two.
#
# Exit condition, stated: a successful LLM call for the same agent, a change
# to the department model candidate list (an operator model swap), or the
# quarantine window elapsing.

_LLM_FAILURE_LOCK = threading.Lock()
_LLM_FAILURES: dict[str, dict[str, float]] = {}
_LLM_FAILURE_KEY_LIMIT = 500


class AgentLLMDeadlock(RuntimeError):
    """The same department-LLM failure repeated past its limit inside a window.

    At this point the worker stops re-attempting the doomed call, records an
    outage on the router's health surface, and returns a failed step whose text
    names the model chain that is dead and the exit condition that clears it.
    """


def _llm_deadlock_limits() -> tuple[int, float]:
    """Repeat limit and window for the worker's identical-failure counter.

    Read defensively, in order: a worker-specific knob if an operator ever adds
    one, then the router's own knobs (same class of failure, same fleet, and it
    needs no code change to tune), then the shared defaults. `config.py` is
    outside this brief's file scope, so nothing here requires it.
    """
    settings = None
    try:
        from app.config import settings as _settings

        settings = _settings
    except Exception:  # noqa: BLE001 - a missing config must not disable the exit
        settings = None

    def _read(name: str, default: Any) -> Any:
        if settings is None:
            return default
        return getattr(settings, name, default)

    try:
        limit = int(
            _read(
                "agent_worker_deadlock_repeat_limit",
                _read("router_deadlock_repeat_limit", 3),
            )
            or 3
        )
    except (TypeError, ValueError):
        limit = 3
    try:
        window = float(
            _read(
                "agent_worker_deadlock_repeat_window_sec",
                _read("router_deadlock_repeat_window_sec", 300.0),
            )
            or 300.0
        )
    except (TypeError, ValueError):
        window = 300.0
    return max(1, limit), max(1.0, window)


def _llm_failure_class(error_text: str) -> str:
    """Fold one failure message onto a stable, comparable class.

    Over-normalising would merge genuinely different failures — an HTTP status is
    the most common way two provider failures differ, so masking every digit
    would let a dead id (404) and a throttled fleet (429) quarantine each other.
    Under-normalising would make every tick a new signature and the loop would
    never be seen. So only the variable parts are folded: long hex ids and digit
    runs of four or more (timestamps, epochs, request ids). Short numbers —
    status codes and counts — are part of the failure and are kept.
    """
    text = str(error_text or "").strip().lower()
    if not text:
        return "unknown"
    text = re.sub(r"\b[0-9a-f]{16,}\b", "<hex>", text)
    text = re.sub(r"\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}[^\s]*", "<ts>", text)
    text = re.sub(r"\b\d{4,}\b", "<num>", text)
    text = re.sub(r"\s+", " ", text)
    return text[:160]


def _llm_failure_signature(
    agent_id: str,
    model_chain: list[str] | tuple[str, ...],
    error_text: str,
    *,
    model: str = "",
) -> str:
    """Stable key for *this* agent failing *this* way on *this* model.

    Deliberately excludes the step id, the goal id and any timestamp: a step is
    recreated or re-claimed every tick, and the loop is precisely the case where
    those differ while nothing else does. It *includes* the model id, so one dead
    id in a chain cannot be masked by, or mask, a healthy sibling.
    """
    chain = ",".join(sorted(str(m) for m in (model_chain or ()) if m))[:400]
    parts = [
        str(agent_id or ""),
        str(model or ""),
        chain,
        _llm_failure_class(error_text),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{str(agent_id or '')}~{digest}"


def _model_chain_signature(agent_id: str, model_chain: Any) -> str:
    """Stable key for "this agent's chain", independent of which error it threw."""
    chain = ",".join(sorted(str(m) for m in (model_chain or ()) if m))[:400]
    digest = hashlib.sha256(
        "|".join([str(agent_id or ""), chain, "chain"]).encode("utf-8")
    ).hexdigest()[:16]
    return f"{str(agent_id or '')}~{digest}"


def note_model_chain_strikes(agent_id: str, model_chain: Any) -> int:
    """Record one fruitless entry into this chain; return the tick strike count.

    One entry into the tick can fail on several models (a chain is tried in
    order), so the loop's own *decision* state is kept per model and per failure
    class — one dead id must not be masked by a healthy sibling, and a dead id
    must not be quarantined by an unrelated transient error. This is the
    operator-facing roll-up: one strike per entry in which the whole chain was
    tried and none of it worked, which is the cadence the tick loop repeats at.
    """
    return _note_llm_failure(_model_chain_signature(agent_id, model_chain))


def model_chain_deadlock_strikes(agent_id: str, model_chain: Any) -> int:
    """Chain-level strike count inside the window, 0 when it has never failed."""
    return _llm_deadlock_open(_model_chain_signature(agent_id, model_chain))


def _max_model_strikes(agent_id: str, model_chain: Any) -> int:
    """Highest identical-(model, class) strike count in this chain, or 0.

    This is what decides the quarantine. It is a *max over per-model keys*, not a
    sum over failures, for one reason: the exit must fire on an identical repeat
    and must not fire when the errors keep changing. Summing would let three
    different failures (404, then 429, then a timeout) add up to a quarantine,
    and the operator would be told a dead model was quarantined when the model
    was in fact intermittently reachable.
    """
    now = time.time()
    _limit, window = _llm_deadlock_limits()
    prefix = f"{str(agent_id or '')}~"
    chain_key = _model_chain_signature(agent_id, model_chain)
    highest = 0
    with _LLM_FAILURE_LOCK:
        for key, entry in _LLM_FAILURES.items():
            if key == chain_key or not key.startswith(prefix) or not prefix.strip("~"):
                continue
            if (now - float(entry.get("first_ts") or 0.0)) > window:
                continue
            highest = max(highest, int(entry.get("count") or 0))
    return highest


def _llm_deadlock_open(signature: str) -> int:
    """Identical-failure count inside the window; 0 when cleared or expired."""
    _limit, window = _llm_deadlock_limits()
    now = time.time()
    with _LLM_FAILURE_LOCK:
        entry = _LLM_FAILURES.get(signature)
        if not entry:
            return 0
        if (now - float(entry.get("first_ts") or 0.0)) > window:
            _LLM_FAILURES.pop(signature, None)
            return 0
        return int(entry.get("count") or 0)


def _note_llm_failure(signature: str) -> int:
    """Count one identical failure and return the new count inside the window."""
    _limit, window = _llm_deadlock_limits()
    now = time.time()
    with _LLM_FAILURE_LOCK:
        entry = _LLM_FAILURES.get(signature)
        if entry is None or (now - float(entry.get("first_ts") or 0.0)) > window:
            entry = {"count": 0.0, "first_ts": now, "last_ts": now}
        entry["count"] = float(entry.get("count") or 0.0) + 1.0
        entry["last_ts"] = now
        _LLM_FAILURES[signature] = entry
        if len(_LLM_FAILURES) > _LLM_FAILURE_KEY_LIMIT:
            for key in [
                k
                for k, v in _LLM_FAILURES.items()
                if (now - float(v.get("last_ts") or 0.0)) > window
            ]:
                _LLM_FAILURES.pop(key, None)
        return int(entry["count"])


def _llm_deadlock_exit_condition(agent_id: str) -> str:
    return (
        "exit: a successful LLM call for this agent, a change to the "
        "department model candidate list (an operator model swap), or the "
        "quarantine window elapsing"
    )


def _record_llm_outage(reason: str, **detail: Any) -> None:
    """Publish a worker LLM outage on the router's own health surface.

    Reuses `smart_router.record_router_outage` rather than building a second
    observability path, so `get_router_health()['failures']['outages']` is the
    one place an operator reads AI outages from. Never raises: a monitoring
    helper must not be the thing that breaks the tick.
    """
    try:
        from app.services.smart_router import record_router_outage

        record_router_outage(reason, **detail)
    except Exception:  # noqa: BLE001
        log.error(
            "agent_worker LLM outage (router health unavailable): %s %s",
            reason,
            detail,
        )


def _clear_llm_failures_for(agent_id: str) -> None:
    """A successful call clears the deadlock counters that share its agent."""
    prefix = f"{str(agent_id or '')}~"
    if prefix == "~":
        return
    with _LLM_FAILURE_LOCK:
        for key in [k for k in _LLM_FAILURES if k.startswith(prefix)]:
            _LLM_FAILURES.pop(key, None)


def clear_llm_deadlock_failures() -> None:
    """Forget the worker deadlock counters (tests, and after a model swap)."""
    with _LLM_FAILURE_LOCK:
        _LLM_FAILURES.clear()


def llm_deadlock_limits() -> tuple[int, float]:
    """Public name for the repeat limit and window this worker enforces."""
    return _llm_deadlock_limits()


def llm_deadlock_snapshot() -> dict[str, Any]:
    """The worker's own view of the counter, for tests and diagnostics.

    Reports only strikes that are still inside the window, so a reader can never
    see a quarantine that has already expired.
    """
    limit, window = _llm_deadlock_limits()
    now = time.time()
    with _LLM_FAILURE_LOCK:
        live = {
            key: dict(entry)
            for key, entry in _LLM_FAILURES.items()
            if (now - float(entry.get("first_ts") or 0.0)) <= window
        }
    return {
        "repeat_limit": limit,
        "window_sec": window,
        "tracked_signatures": len(live),
        "signatures": live,
    }


# ── Closed loop: a tool that keeps FAILING must have an exit ───────────────
#
# FU9. `work_sessions.id = 76890` (started 2026-09-28T19:14:58, 18 tool calls over
# 7 tools, `11 of 5` work steps, status `failed`) ended on `[TIMEOUT after 407s]`
# with no verdict: `upgrade_tool` failed at step 4, `code_edit` failed at step 8,
# and steps 9-11 went back to `upgrade_tool`. The model's *prose* changed every
# step; the failing tool and its error did not.
#
# Nothing counted that, and no existing guard can see it:
#   * the block above counts failures of the LLM CALL, and a call that comes back
#     carrying a failing tool call is a *success* -- `_clear_llm_failures_for`
#     (:2405 on the Copilot tier, :2537 on the gateway tier) RESETS it, so the
#     failing-tool loop actively clears the one counter that is running;
#   * `_tick_action_counts` (:2720) counts tool CALLS, never their outcome, and is
#     rebuilt per `_execute_llm_step` call, so it cannot span a session;
#   * `cost_circuit_breaker.check_duplicate_tools` (:480) and
#     `anomaly_detector._check_runaway_loop` (:254) both `continue` on
#     `executed is False` -- a failed call is filtered out of both by construction;
#   * the prose stall guard requires `not actions` (`app/autopilot.py`:4000), and
#     every step of that loop executed 1-2 actions, so it could never fire.
#
# So this mirrors the shape above -- one module-global, window-bounded counter, a
# strike keyed on the failure class, a refusal checked *before* the doomed call,
# and a named terminal verdict -- rather than inventing a second mechanism.
#
# Exit condition, stated: a successful call to this tool, a tool this agent has not
# been failing on, or the loop window elapsing.

_TOOL_FAILURE_LOCK = threading.Lock()
_TOOL_FAILURES: dict[str, dict[str, Any]] = {}
_TOOL_FAILURE_KEY_LIMIT = 500


class ToolLoopDeadlock(RuntimeError):
    """The same tool failing identically past its limit inside a window.

    The named verdict this file returns. Nothing raises it: the exit is a recorded
    `StepResult`, because the callers of `_execute_llm_step` catch broad exceptions
    and a raise would lose the verdict text -- the same reason `AgentLLMDeadlock`
    above is named rather than thrown. `marker` is the greppable form, so it reads
    the same way as this codebase's other terminal verdicts
    (`[STEP_BUDGET_EXHAUSTED: ...]`, `[STALLED_REPEATING_OUTPUT]`).
    """

    marker = "TOOL_LOOP_DEADLOCK"


def _tool_deadlock_limits() -> tuple[int, float]:
    """Repeat limit and window for the worker's identical-tool-failure counter.

    Read defensively, in order: a tool-specific knob if an operator adds one, then
    the router's own knobs (same class of failure, same fleet, and it needs no code
    change to tune), then the shared defaults. `config.py` is outside this brief's
    file scope, so nothing here requires it; the two names below belong there.
    """
    settings = None
    try:
        from app.config import settings as _settings

        settings = _settings
    except Exception:  # noqa: BLE001 - a missing config must not disable the exit
        settings = None

    def _read(name: str, default: Any) -> Any:
        if settings is None:
            return default
        return getattr(settings, name, default)

    try:
        limit = int(
            _read(
                "agent_worker_tool_loop_repeat_limit",
                _read("router_deadlock_repeat_limit", 3),
            )
            or 3
        )
    except (TypeError, ValueError):
        limit = 3
    try:
        window = float(
            _read(
                "agent_worker_tool_loop_repeat_window_sec",
                _read("router_deadlock_repeat_window_sec", 300.0),
            )
            or 300.0
        )
    except (TypeError, ValueError):
        window = 300.0
    return max(1, limit), max(1.0, window)


def _tool_failure_class(error_text: str) -> str:
    """Fold one tool failure onto a stable, comparable class.

    Same rule as `_llm_failure_class` -- keep the failure, fold only the volatile
    parts -- with one addition, because a tool error carries a variable a provider
    error does not: the *target*. `code_edit` failing on `app/main.py` and failing
    on `app/autopilot.py` with the same message is one failure being re-attempted
    against a different target, and it must count as one loop, not as two new
    failures. So file paths are folded, in three passes so that an absolute path, a
    relative path and a bare filename all land on the same token:

      1. any path ending in a known source/doc extension -> `<path>`
         (`app/main.py`, `app/services/agent_worker.py`, `docs/co/X.md`,
         `/srv/a/b/c.py` -- all one token now);
      2. a bare filename with such an extension -> `<file>`;
      3. an extensionless absolute path -> `<path>`.

    Not folded: short numbers. An exit code, an HTTP status and a count are part of
    the failure; masking every digit is how a dead target and a throttled one would
    end up quarantining each other. Pass 3 is anchored on a leading separator or a
    drive letter on purpose, so `404/500` is not mistaken for a path.
    """
    text = _llm_failure_class(error_text)
    if not text or text == "unknown":
        return "unknown"
    _ext = (
        r"(?:py|pyi|json|jsonl|md|txt|log|sh|ps1|toml|yml|yaml|ts|tsx|js|jsx"
        r"|sql|cfg|ini|csv|xml|html|css)"
    )
    text = re.sub(rf"[\w.\-]*(?:[\\/][\w.\-]*)+\.{_ext}\b", "<path>", text)
    text = re.sub(rf"\b[\w.\-]+\.{_ext}\b", "<file>", text)
    text = re.sub(r"(?:[a-z]:[\\/]|[\\/])(?:[\w.\-]+[\\/])+[\w.\-]+", "<path>", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()[:160]


# ── P3: the response to a repeated tool failure depends on WHAT failed ──────
# "Failed three times" is not one condition. A missing dependency (the script or
# interpreter is not there -- `rc=127`, `command not found`, `not configured`) can
# never be retried into existence: escalating with the exact stderr is the only
# honest move. An argument error names a bad parameter and CAN be fixed, so it gets
# one retry with the error text fed back. Everything else is a change-strategy
# stall. The classes are ordered so the permanent one wins if a message contains
# both kinds of wording.
_MISSING_DEPENDENCY_MARKERS = (
    "rc=127",
    "command not found",
    "commandnotfound",
    "not found",
    "no such file",
    "not configured",
    "is not recognized",
    "cannot find",
    "module not found",
    "no module named",
    "executable file not found",
)
_ARGUMENT_ERROR_MARKERS = (
    "invalid argument",
    "unexpected keyword",
    "missing required",
    "bad parameter",
    "unknown parameter",
    "argument error",
    "requires a value",
    "expected type",
    "invalid value",
    "must be one of",
    "not a valid",
    "no such option",
    "unknown option",
)


def classify_tool_failure(error_text: str) -> str:
    """Fold a tool failure onto the response it licenses.

    Returns one of ``"missing_dependency"`` (not retryable -- escalate now),
    ``"argument"`` (one fed-back retry), or ``"other"`` (a change-strategy stall).
    An empty error is ``"other"``: not knowing why it failed is not evidence that
    it is permanent.
    """
    text = str(error_text or "").strip().lower()
    if not text:
        return "other"
    if any(marker in text for marker in _MISSING_DEPENDENCY_MARKERS):
        return "missing_dependency"
    if any(marker in text for marker in _ARGUMENT_ERROR_MARKERS):
        return "argument"
    return "other"


def _tool_scope_prefix(agent_id: str, tool_name: str) -> str:
    """Key prefix for *this* agent failing *this* tool, whatever the error was."""
    return f"{str(agent_id or '')}~{str(tool_name or '')}~"


def _tool_failure_signature(agent_id: str, tool_name: str, error_text: str) -> str:
    """Stable key for *this* agent failing *this* tool *this* way.

    Deliberately excludes the step id, the goal id, the tool arguments and any
    timestamp: the loop is precisely the case where those differ every attempt --
    the same failing call is re-issued with re-serialised args each round -- so
    keying on them would make every attempt a new signature and the loop would
    never be seen. It *includes* the agent and the tool, so one department's dead
    tool cannot mask, or be masked by, another's.
    """
    parts = [
        str(agent_id or ""),
        str(tool_name or ""),
        _tool_failure_class(error_text),
    ]
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()[:16]
    return f"{_tool_scope_prefix(agent_id, tool_name)}{digest}"


def _tool_deadlock_state(agent_id: str, tool_name: str) -> dict[str, Any]:
    """Live strike state for one (agent, tool): the highest class count, and it.

    A *max over per-class keys*, not a sum over failures -- the same decision rule
    as `_max_model_strikes`, for the same reason: three identical failures are a
    loop and quarantine; three different ones are new evidence each time and must
    not add up to a quarantine the operator would be told was a repeated failure.
    """
    now = time.time()
    _limit, window = _tool_deadlock_limits()
    prefix = _tool_scope_prefix(agent_id, tool_name)
    best: dict[str, Any] = {"strikes": 0, "failure_class": "", "last_error": ""}
    if prefix == "~~":
        return best
    with _TOOL_FAILURE_LOCK:
        for key, entry in list(_TOOL_FAILURES.items()):
            if not key.startswith(prefix):
                continue
            if (now - float(entry.get("first_ts") or 0.0)) > window:
                continue
            count = int(float(entry.get("count") or 0))
            if count > int(best["strikes"]):
                best = {
                    "strikes": count,
                    "failure_class": str(entry.get("failure_class") or ""),
                    "last_error": str(entry.get("last_error") or ""),
                }
    return best


def _tool_deadlock_open(signature: str) -> int:
    """Identical-failure count inside the window; 0 when cleared or expired."""
    _limit, window = _tool_deadlock_limits()
    now = time.time()
    with _TOOL_FAILURE_LOCK:
        entry = _TOOL_FAILURES.get(signature)
        if not entry:
            return 0
        if (now - float(entry.get("first_ts") or 0.0)) > window:
            _TOOL_FAILURES.pop(signature, None)
            return 0
        return int(float(entry.get("count") or 0))


def _note_tool_failure(agent_id: str, tool_name: str, error_text: str) -> int:
    """Count one failed call of this tool and return the new class count.

    Called from exactly one place -- the branch of `_execute_tool_with_autonomy`
    that has already excluded the two "the tool never ran" returns -- so a scope
    refusal and an approval queueing are never counted as failures of the tool.
    """
    if not str(tool_name or "").strip():
        return 0
    _limit, window = _tool_deadlock_limits()
    now = time.time()
    signature = _tool_failure_signature(agent_id, tool_name, error_text)
    with _TOOL_FAILURE_LOCK:
        entry = _TOOL_FAILURES.get(signature)
        if entry is None or (now - float(entry.get("first_ts") or 0.0)) > window:
            entry = {"count": 0.0, "first_ts": now, "last_ts": now}
        entry["count"] = float(entry.get("count") or 0.0) + 1.0
        entry["last_ts"] = now
        entry["last_error"] = str(error_text or "")[:400]
        entry["failure_class"] = _tool_failure_class(error_text)
        entry["agent_id"] = str(agent_id or "")
        entry["tool"] = str(tool_name or "")
        _TOOL_FAILURES[signature] = entry
        if len(_TOOL_FAILURES) > _TOOL_FAILURE_KEY_LIMIT:
            for key in [
                k
                for k, v in _TOOL_FAILURES.items()
                if (now - float(v.get("last_ts") or 0.0)) > window
            ]:
                _TOOL_FAILURES.pop(key, None)
        return int(entry["count"])


def _clear_tool_failures_for(agent_id: str, tool_name: str) -> None:
    """A successful call clears the loop counters for that tool.

    Exit condition #1, and the reason a tool that fails once and later succeeds is
    never quarantined: the success removes the evidence.
    """
    prefix = _tool_scope_prefix(agent_id, tool_name)
    if prefix == "~~":
        return
    with _TOOL_FAILURE_LOCK:
        for key in [k for k in _TOOL_FAILURES if k.startswith(prefix)]:
            _TOOL_FAILURES.pop(key, None)


def clear_tool_loop_failures() -> None:
    """Forget the tool-loop counters (tests, and after an operator tool fix)."""
    with _TOOL_FAILURE_LOCK:
        _TOOL_FAILURES.clear()


def tool_loop_limits() -> tuple[int, float]:
    """Public name for the repeat limit and window this worker enforces."""
    return _tool_deadlock_limits()


def tool_loop_snapshot() -> dict[str, Any]:
    """The worker's own view of the tool counter, for tests and diagnostics.

    Reports only strikes that are still inside the window, so a reader can never
    see a quarantine that has already expired -- and reports the verdict's own
    name, so a monitor can label the stop without parsing the text.
    """
    limit, window = _tool_deadlock_limits()
    now = time.time()
    with _TOOL_FAILURE_LOCK:
        live = {
            key: dict(entry)
            for key, entry in _TOOL_FAILURES.items()
            if (now - float(entry.get("first_ts") or 0.0)) <= window
        }
    return {
        "repeat_limit": limit,
        "window_sec": window,
        "verdict": ToolLoopDeadlock.marker,
        "tracked_signatures": len(live),
        "signatures": live,
    }


def _tool_loop_exit_condition() -> str:
    return (
        "exit: a successful call to this tool, a tool this agent has not been "
        "failing on, or the loop window elapsing"
    )


def _tool_loop_deadlock_summary(
    agent_id: str,
    tool_name: str,
    state: dict[str, Any],
    *,
    called: bool,
) -> str:
    """The named, terminal verdict for a tool the session kept re-failing.

    Says all four things a reader needs and the timeout never said: which tool,
    how many identical failures, what the last error was, and what would clear it.
    """
    limit, window = _tool_deadlock_limits()
    strikes = int(state.get("strikes") or 0)
    cls = str(state.get("failure_class") or "unknown")
    last = " ".join(str(state.get("last_error") or "").split())[:200]
    attempted = (
        "0 calls attempted - another attempt is guaranteed to fail the same way "
        "and is not made"
        if not called
        else "the call that reached the limit was not retried"
    )
    return (
        f"[{ToolLoopDeadlock.marker}: '{tool_name}' failed identically "
        f"{strikes}/{limit} times for {agent_id} in the last {window:.0f}s "
        f"(failure_class={cls})] {attempted} ({_tool_loop_exit_condition()}). "
        f"Last error: {last or 'unknown'}"
    )


def _extract_required_tools(description: str) -> list[str]:
    """Extract one or more REQUIRED TOOL hints from a step description."""
    marker = "REQUIRED TOOL:"
    if marker not in description:
        return []

    idx = description.index(marker) + len(marker)
    tail = description[idx:]
    end = tail.find(".")
    if end >= 0:
        tail = tail[:end]

    normalized = tail.replace(" or ", " OR ")
    raw_parts = [part.strip() for part in normalized.split(" OR ")]
    tools: list[str] = []

    for part in raw_parts:
        if not part:
            continue
        token = part.split("(", 1)[0].strip()
        token = token.split(",", 1)[0].strip()
        token = token.split(" ", 1)[0].strip()
        if token:
            tools.append(token)

    return tools


def _build_repo_alias_guidance(agent_id: str) -> str:
    """Return a compact repo alias guide for department prompts."""
    try:
        from app.company_blueprint import (
            get_repos_for_department,
        )
        from app.chat_action_repos import resolve_managed_repo_path

        aliases = get_repos_for_department(agent_id)
        if not aliases:
            return ""

        repo_lines: list[str] = []
        for alias in aliases:
            path, exists, _hint = resolve_managed_repo_path(alias)
            if path and exists:
                repo_lines.append(f"- {alias} -> {path}")
            elif path:
                repo_lines.append(
                    f"- {alias} -> {path} (not on this host; use github_* tools)"
                )
            else:
                repo_lines.append(f"- {alias}")

        if not repo_lines:
            return ""

        return "\n".join(
            [
                "Repository aliases you can use for repo_path:",
                *repo_lines,
                ("For repo_run_command, always provide BOTH " "repo_path and command."),
            ]
        )
    except Exception:
        return ""


def _missing_required_tool_fields(
    tool_name: str,
    tool_args: dict[str, Any],
    tools: list[dict[str, Any]] | None,
) -> list[str]:
    """Return any required schema fields missing from a tool call."""
    if not tools:
        return []

    for schema in tools:
        if schema.get("name") != tool_name:
            continue
        params = schema.get("parameters") or {}
        required = params.get("required") or []
        missing: list[str] = []
        for field_name in required:
            value = tool_args.get(field_name)
            if value is None:
                missing.append(str(field_name))
            elif isinstance(value, str) and not value.strip():
                missing.append(str(field_name))
        return missing
    return []


def _track_real_output(
    tool_name: str,
    agent_id: str,
    settings: Any,
) -> None:
    """Log external-facing tool executions for value tracking."""
    if tool_name not in _REAL_OUTPUT_ACTIONS:
        return
    try:
        from app.database import _db_lock, _get_conn

        conn = _get_conn(settings.database_url)
        with _db_lock:
            conn.execute(
                "INSERT INTO activity_log "
                "(agent_id, action, detail, created_at) "
                "VALUES (?, ?, ?, "
                "strftime('%Y-%m-%dT%H:%M:%SZ','now'))",
                (
                    agent_id,
                    f"real_output:{tool_name}",
                    f"Agent {agent_id} executed {tool_name}",
                ),
            )
            _commit(conn)
    except Exception:
        pass


@dataclass
class StepResult:
    """Result from executing a single goal step."""

    action: str = "complete"  # complete, skip, escalate, error, suspended
    result_summary: str = ""
    next_step_context: str | None = None
    tokens_in: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    duration_ms: int = 0
    tools_used: list[str] = field(default_factory=list)
    tools_executed: list[str] = field(default_factory=list)
    tool_call_details: list[dict[str, Any]] = field(default_factory=list)
    tool_rounds: int = 0
    approval_ids: list[str] = field(default_factory=list)


@dataclass
class TickOutcome:
    """Result of a productive agent tick."""

    agent_id: str
    status: str  # completed, idle, error, budget_exceeded
    step_id: int | None = None
    goal_id: str | None = None
    result: StepResult | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


def _build_tick_event_payload(
    agent_id: str,
    step: dict[str, Any],
    result: StepResult,
    tick_outcome: str,
) -> tuple[str, int, dict[str, Any]]:
    """Build a proactive event payload from a real productive tick."""
    step_title = str(step.get("title") or "current step")
    payload = {
        "agent_id": agent_id,
        "goal_id": step.get("goal_id"),
        "step_id": step.get("id"),
        "step_title": step_title,
        "action": result.action,
        "tools_executed": result.tools_executed[:5],
        "summary": result.result_summary[:500],
    }
    if tick_outcome == "success":
        return "task_completed", 2, payload
    return "error_spike", 1, payload


def _build_tick_learning_rule(
    step: dict[str, Any],
    result: StepResult,
    tick_outcome: str,
) -> dict[str, Any] | None:
    """Turn a concrete tick outcome into a small reusable rule."""
    step_title = str(step.get("title") or "current step").strip()

    if tick_outcome == "success" and result.tools_executed:
        sample_tools = ", ".join(result.tools_executed[:3])
        return {
            "rule_type": "action",
            "condition": ("When a goal step is active and the next action is clear"),
            "action_text": (
                "Use concrete tools to move the work forward. "
                f"Recent successful tools included {sample_tools}."
            ),
            "reason": f"This pattern succeeded on step '{step_title}'.",
            "source_task_type": "productive_tick",
            "initial_confidence": 0.58,
        }

    if tick_outcome == "failure" and not result.tools_executed:
        return {
            "rule_type": "constraint",
            "condition": (
                "When a goal step is active but you are uncertain " "or blocked"
            ),
            "action_text": (
                "Do not end the tick with only meta commentary. "
                "Execute a concrete tool or escalate the blocker explicitly."
            ),
            "reason": (
                f"A recent productive tick failed on step '{step_title}' "
                "without effective tool execution."
            ),
            "source_task_type": "productive_tick",
            "initial_confidence": 0.66,
        }

    return None


def _build_tick_knowledge_text(
    agent_id: str,
    step: dict[str, Any],
    result: StepResult,
    tick_outcome: str,
) -> str:
    """Compose a compact knowledge-graph text episode from a tick."""
    parts = [
        f"Agent {agent_id} worked on goal {step.get('goal_id') or 'unknown'}.",
        f"Step: {step.get('title') or 'Untitled step'}.",
        f"Outcome: {tick_outcome} via action {result.action}.",
    ]

    description = str(step.get("description") or "").strip()
    if description:
        parts.append(f"Context: {description[:400]}")

    if result.result_summary:
        parts.append(f"Result: {result.result_summary[:600]}")

    if result.next_step_context:
        parts.append(f"Next context: {result.next_step_context[:400]}")

    return " ".join(parts)


def _record_cognitive_artifacts(
    agent_id: str,
    step: dict[str, Any],
    result: StepResult,
    tick_outcome: str,
) -> None:
    """Emit D019 artifacts from a live productive tick without breaking it."""
    try:
        from app.services.proactive_engine import ingest_event

        event_type, priority, payload = _build_tick_event_payload(
            agent_id,
            step,
            result,
            tick_outcome,
        )
        ingest_event(
            event_type,
            "agent_worker",
            payload,
            priority=priority,
            dedup_key=(
                f"tick:{agent_id}:{step.get('goal_id')}:{step.get('id')}:"
                f"{tick_outcome}:{result.action}"
            ),
        )
    except Exception:
        pass

    try:
        from app.services.behavioral_rules import store_rule

        rule = _build_tick_learning_rule(step, result, tick_outcome)
        if rule:
            store_rule(agent_id=agent_id, **rule)
    except Exception:
        pass

    try:
        from app.services.knowledge_graph import ingest_text

        knowledge_text = _build_tick_knowledge_text(
            agent_id,
            step,
            result,
            tick_outcome,
        )
        if knowledge_text.strip():
            ingest_text(knowledge_text, source="agent_tick")
    except Exception:
        pass


# ── Step claiming ──────────────────────────────────────────────────────


def claim_next_step(db_url: str, agent_id: str) -> dict[str, Any] | None:
    """Atomically claim the next pending step for this agent.

    Returns the step row dict or None if nothing available.

    Anti-loop guard: steps released by pre-flight skip / meta-only burn-out
    get `completed_at` set at release time. They are excluded from claiming
    for RELEASED_STEP_COOLDOWN_MINUTES so the agent does not re-claim the
    same dead step every tick while healthy work behind it starves. Legit
    recovery paths (`reset_blocked_required_tool_steps`, and the lifecycle
    sweep's `_reopen_stale_blocked_steps`) clear `completed_at`/attempts
    and reopen them.

    FIX (2026-08-30): 'blocked' steps are NO LONGER claimable here. They
    were re-claimed after the cooldown, but `_should_skip_step` Check 4
    (stale meta-only error + attempts >= threshold) instantly re-blocked
    them — an infinite 30-min claim/skip/release churn that refreshed
    `completed_at` every cycle, so the step NEVER got a real LLM call and
    the sweep's reopen cooldown could never elapse. Blocked steps now only
    reopen through the lifecycle sweep (`_reopen_stale_blocked_steps`) or
    an explicit recovery path.
    """
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)

    # Find highest-priority pending step assigned to this agent
    step = conn.execute(
        f"""
        SELECT gs.*, gp.title AS goal_title, gp.objective,
               gp.priority AS goal_priority,
               gp.source AS goal_source, gp.origin_source AS goal_origin
        FROM goal_steps gs
        JOIN goal_plans gp ON gs.goal_id = gp.id
        WHERE gp.assigned_agent = ?
          AND gp.status = 'active'
          AND gs.status = 'pending'
          AND gs.claimed_by IS NULL
          AND (
              gs.completed_at IS NULL
              OR gs.completed_at < strftime(
                  '%Y-%m-%dT%H:%M:%S',
                  'now',
                  ?)
          )
        ORDER BY gp.priority DESC, gs.step_number ASC
        LIMIT 1
        """,
        (agent_id, f"-{RELEASED_STEP_COOLDOWN_MINUTES} minutes"),
    ).fetchone()

    if not step:
        return None

    step = dict(step)
    now_iso = _utc_now().isoformat()

    # Atomic claim
    with _db_lock:
        affected = conn.execute(
            """
            UPDATE goal_steps
            SET claimed_by = ?, status = 'running',
                started_at = ?
            WHERE id = ? AND claimed_by IS NULL
            """,
            (agent_id, now_iso, step["id"]),
        ).rowcount
        _commit(conn)

    if affected == 0:
        return None  # Someone else claimed it

    step["claimed_by"] = agent_id
    step["started_at"] = now_iso
    return step


def release_stale_claims(db_url: str) -> int:
    """Reset steps that have been claimed too long without completing.

    Returns count of released steps.
    """
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)
    cutoff = _utc_now() - timedelta(minutes=STALE_CLAIM_MINUTES)
    cutoff_iso = cutoff.isoformat()

    with _db_lock:
        # Find steps claimed more than STALE_CLAIM_MINUTES ago
        cur = conn.execute(
            """
            UPDATE goal_steps
            SET status = 'pending', claimed_by = NULL,
                attempts = attempts + 1
            WHERE status = 'running'
              AND claimed_by IS NOT NULL
              AND started_at < ?
            """,
            (cutoff_iso,),
        )
        _commit(conn)

    if cur.rowcount:
        log.info("Released %d stale step claims", cur.rowcount)
    return cur.rowcount


# ── Context building ───────────────────────────────────────────────────


def _build_perf_context(agent_id: str) -> str:
    """Build a brief performance summary from recent tick quality data.

    D013: Injected into agent prompts so they can self-correct.
    Returns empty string if data unavailable.
    """
    try:
        from app.services.tick_quality import (
            check_consecutive_failures,
            get_agent_quality_stats,
        )
        from app.config import settings

        db_url = settings.database_url
        stats = get_agent_quality_stats(db_url, agent_id, hours=4)
        if stats["total"] == 0:
            return ""

        parts = [
            f"Recent performance ({stats['total']} ticks, 4h):",
            f"  quality={stats['quality_index']:.0%}",
            f"  productive={stats['productive']}",
            f"  failed={stats['failed']}",
        ]

        if check_consecutive_failures(db_url, agent_id, threshold=3):
            parts.append(
                "  WARNING: 3+ consecutive failures — " "try a different approach."
            )
        return " ".join(parts)
    except Exception:  # noqa: BLE001
        return ""


def build_focused_prompt(
    step: dict[str, Any],
    agent_id: str,
    working_memory: str | None = None,
    prev_step_output: str | None = None,
    tool_names: list[str] | None = None,
) -> list[dict[str, str]]:
    """Build a focused prompt with department context and tool guidance.

    Includes department blueprint context and instructs the LLM
    to use structured tool_calls (not JSON text responses).
    """
    # Get department context from blueprint
    dept_context = ""
    try:
        from app.company_blueprint import build_department_context

        dept_context = build_department_context(agent_id)
    except Exception:
        pass

    system_parts = [
        f"You are the {agent_id} department agent.",
    ]

    if dept_context:
        system_parts.append(f"\n{dept_context}")

    system_parts.extend(
        [
            f"\nGoal: {step.get('goal_title', 'Unknown')}",
            f"Objective: {step.get('objective', '')}",
            "",
            f"Execute step {step.get('step_number', '?')}: "
            f"{step.get('title', 'Unknown step')}",
            f"Description: {step.get('description', 'No details')}",
        ]
    )

    # D017: Inject meta-only feedback from previous failed attempts
    error_msg = step.get("error_message") or ""
    if "meta-only" in error_msg.lower() or "Meta-only" in error_msg:
        # Extract the REQUIRED TOOL hint from description if present
        desc = step.get("description", "")
        tool_hint = ""
        if "REQUIRED TOOL:" in desc:
            hint_start = desc.index("REQUIRED TOOL:") + 15
            hint_end = desc.find(".", hint_start)
            if hint_end > hint_start:
                tool_hint = desc[hint_start:hint_end].strip()
        tool_msg = (
            f" You MUST call {tool_hint}"
            if tool_hint
            else " You MUST call a productive tool"
        )
        system_parts.append(
            f"\n⚠️ PREVIOUS ATTEMPT FAILED: {error_msg}. "
            f"{tool_msg} this time. "
            "Do NOT use only save_memory or update_progress."
        )

    if working_memory:
        system_parts.append(f"\nWorking memory: {working_memory}")

    if prev_step_output:
        system_parts.append(f"\nPrevious step result: {prev_step_output}")

    input_json = step.get("input_json")
    if input_json and input_json != "{}":
        system_parts.append(f"\nInput data: {input_json}")

    required_tools = _extract_required_tools(step.get("description", ""))
    if required_tools:
        required_msg = ", ".join(required_tools)
        system_parts.extend(
            [
                "",
                "STEP-SPECIFIC REQUIREMENT:",
                (
                    "- Your first concrete tool call for this step "
                    f"must be one of: {required_msg}"
                ),
                (
                    "- Do not substitute a different tool before "
                    "satisfying that requirement."
                ),
            ]
        )

    # Tool usage instructions
    if tool_names:
        names_str = ", ".join(tool_names)
        system_parts.extend(
            [
                "",
                "Use tool calls to execute real work.",
                f"Available tools: {names_str}",
                "",
                "CRITICAL RULES:",
                "1. You MUST call at least one productive tool per step "
                "(e.g. close_task, create_task, send_sms, gmail_send, "
                "github_write_file, calendar_create, ha_call_service, code_edit).",
                "2. save_memory and web_search alone are NOT enough "
                "— they must support a concrete action.",
                "3. When your step completes the goal, call close_task "
                "on the parent task to mark it done.",
                "4. If you cannot complete the step, explain why "
                "— do NOT just save a memory and call it done.",
                "",
                "When done, respond with a text summary of what you accomplished.",
            ]
        )
        if any(name.startswith("repo_") for name in tool_names):
            repo_guidance = _build_repo_alias_guidance(agent_id)
            if repo_guidance:
                system_parts.extend(["", repo_guidance])
    else:
        system_parts.extend(
            [
                "",
                "Respond with a JSON object:",
                '{"action": "complete|skip|escalate",',
                ' "result_summary": "what you accomplished",',
                ' "next_step_context": "context for next step"}',
            ]
        )

    system_parts.append("\nBe concise. Execute, don't just plan.")

    # D013: Inject recent performance context
    perf_ctx = _build_perf_context(agent_id)
    if perf_ctx:
        system_parts.append(f"\n{perf_ctx}")

    return [
        {"role": "system", "content": "\n".join(system_parts)},
        {"role": "user", "content": "Execute this step now."},
    ]


# ── Step completion ────────────────────────────────────────────────────


def complete_step(
    db_url: str,
    step_id: int,
    result: StepResult,
) -> None:
    """Mark a step as completed and store the result summary."""
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)
    now_iso = _utc_now().isoformat()

    status = "completed"
    if result.action == "skip":
        status = "skipped"
    elif result.action == "escalate":
        status = "blocked"
    elif result.action == "error":
        status = "failed"
    elif result.action == "suspended":
        status = "waiting_approval"

    completed_at = now_iso if status not in ("waiting_approval",) else None

    # Clear stale error_message on success so pre-flight skip checks
    # (_should_skip_step Check 4) don't poison future re-attempts with
    # an old "meta-only" error from a resolved root cause.
    error_message = None
    if status in ("failed", "blocked"):
        error_message = result.result_summary

    with _db_lock:
        conn.execute(
            """
            UPDATE goal_steps
            SET status = ?, claimed_by = NULL,
                completed_at = ?,
                result_summary = ?,
                output_json = ?,
                error_message = ?
            WHERE id = ?
            """,
            (
                status,
                completed_at,
                result.result_summary,
                json.dumps(
                    {
                        "action": result.action,
                        "next_context": result.next_step_context,
                        "approval_ids": result.approval_ids,
                    }
                ),
                error_message,
                step_id,
            ),
        )
        _commit(conn)


def _has_productive_tool_use(
    tools_used: list[str],
    step_description: str = "",
    final_response: str = "",
) -> bool:
    """Return True when the tick used at least one non-meta tool.

    If the step description contains a ``REQUIRED TOOL: <name>`` hint and that
    tool was actually called, it counts as productive even if the tool is
    normally in META_ONLY_TOOLS.

    Lookup tools used in a step with REQUIRED TOOL hints also count as
    productive — they are prerequisite work to satisfy the requirement.

    FIX (2026-08-31): intent-aware meta tools. When the step description
    signals that a meta tool IS the deliverable (e.g. a research step that
    calls web_search/fetch_url; a reminder step that calls
    schedule_reminder), that tool counts as productive — the classifier
    was previously intent-blind and falsely blocked real work. A
    substantive final response (>= SUBSTANTIVE_RESPONSE_MIN_CHARS) also
    counts as productive even with only meta tools.
    """
    if not tools_used:
        return False

    # Check for a REQUIRED TOOL hint that exempts a meta tool
    if "REQUIRED TOOL:" in step_description:
        idx = step_description.index("REQUIRED TOOL:") + 15
        end = step_description.find(".", idx)
        if end < 0:
            end = step_description.find(" ", idx + 20)
        if end > idx:
            required = step_description[idx:end].strip().lower()
            for tool_name in tools_used:
                if tool_name.lower() == required:
                    return True
        # Lookup tools used when a step has a required tool hint
        # are prerequisite work — count as productive
        for tool_name in tools_used:
            if tool_name in _LOOKUP_TOOLS_ALWAYS_ALLOWED:
                return True

    desc_lower = (step_description or "").lower()
    for tool_name in tools_used:
        if tool_name not in META_ONLY_TOOLS:
            return True
        # Intent-aware: meta tool is the deliverable for this step type
        intent_keywords = META_TOOL_INTENT_KEYWORDS.get(tool_name, ())
        if any(kw in desc_lower for kw in intent_keywords):
            return True

    # Substantive final response with only meta tools = real synthesized work
    if len((final_response or "").strip()) >= SUBSTANTIVE_RESPONSE_MIN_CHARS:
        return True

    return False


def _mark_unproductive_step(
    db_url: str,
    step_id: int,
    tools_used: list[str],
    *,
    reason: str = "meta_only",
    detail: str = "",
) -> dict[str, Any]:
    """Requeue or escalate a step that produced no usable work.

    `reason` names WHY, and it is written into the step's evidence:
      * ``meta_only``        -- the tick ran, but every tool it used was
                                informational (META_ONLY_TOOLS);
      * ``no_tool_executed`` -- every tool call the step made was refused, so
                                nothing ran at all.

    Before 2026-10-02 both cases wrote the same sentence ("Meta-only tool use did
    not complete the step"), so the quarantine classifier could not tell them
    apart and filed a refused-but-allow-listed tool as "meta-only tool use" --
    the diagnosis a future session reads is only as good as this string.
    """
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)
    row = conn.execute(
        "SELECT attempts, max_retries, output_json FROM goal_steps WHERE id = ?",
        (step_id,),
    ).fetchone()

    attempts = int((row["attempts"] if row else 0) or 0) + 1
    max_retries = int((row["max_retries"] if row else 3) or 3)
    max_retries = max(1, max_retries)
    step_status = "blocked" if attempts >= max_retries else "pending"
    tool_list = ", ".join(str(t) for t in (tools_used or [])) or "none"
    if reason == "no_tool_executed":
        message = (
            "No tool call executed successfully "
            f"(attempt {attempts}/{max_retries}): {tool_list}."
        )
        if detail:
            message += f" Last refusal: {str(detail).strip()[:300]}"
    else:
        message = (
            "Meta-only tool use did not complete the step "
            f"(attempt {attempts}/{max_retries}): {tool_list}."
        )
    if step_status == "blocked":
        message += " Escalating step for review."

    # Preserve the lifecycle reopen counter so the auto-reopen cap
    # (_reopen_stale_blocked_steps) survives re-blocks of the same step.
    reopened_count = 0
    try:
        prev_output = json.loads((row["output_json"] if row else None) or "{}")
        if isinstance(prev_output, dict):
            reopened_count = int(prev_output.get("reopened_count", 0) or 0)
    except (ValueError, TypeError):
        pass

    with _db_lock:
        conn.execute(
            """
            UPDATE goal_steps
            SET status = ?, claimed_by = NULL,
                started_at = NULL, completed_at = ?,
                attempts = ?, error_message = ?,
                result_summary = ?, output_json = ?
            WHERE id = ?
            """,
            (
                step_status,
                _utc_now().isoformat() if step_status == "blocked" else None,
                attempts,
                message,
                message,
                json.dumps(
                    {
                        "action": reason,
                        "tools_used": tools_used,
                        "reopened_count": reopened_count,
                        "detail": str(detail)[:300],
                    }
                ),
                step_id,
            ),
        )
        _commit(conn)

    return {
        "attempts": attempts,
        "message": message,
        "status": step_status,
    }


def _maybe_escalate_blocked_required_tool_step(
    db_url: str,
    agent_id: str,
    step: dict[str, Any],
    result: StepResult,
    retry_state: dict[str, Any] | None,
) -> str | None:
    """Escalate repeated required-tool failures once the step is blocked."""
    if not retry_state or retry_state.get("status") != "blocked":
        return None

    step_desc = str(step.get("description") or "")
    required_tools = _extract_required_tools(step_desc)
    if not required_tools:
        return None

    attempted_tools = result.tools_used or result.tools_executed or []
    attempted_label = (
        ", ".join(str(t) for t in attempted_tools) if attempted_tools else "none"
    )
    failure_detail = (
        retry_state.get("message") or result.result_summary or "step blocked"
    )
    error_text = (
        "Required-tool step blocked after repeated attempts. "
        f"Required tool(s): {', '.join(required_tools)}. "
        f"Attempted tool(s): {attempted_label}. "
        f"Failure: {failure_detail}"
    )

    try:
        from app.services.escalation_router import (
            classify_error,
            route_escalation,
            severity_for_class,
        )

        error_class = classify_error(error_text)
        severity = severity_for_class(error_class)
        action = route_escalation(
            severity,
            agent_id,
            error_text,
            step_id=step.get("id"),
            goal_id=step.get("goal_id"),
            db_url=db_url,
        )
        log.warning(
            "Escalated blocked required-tool step %s for %s via %s",
            step.get("id"),
            agent_id,
            action,
        )
        return action
    except Exception as exc:  # noqa: BLE001
        log.warning(
            "Failed to escalate blocked required-tool step %s for %s: %s",
            step.get("id"),
            agent_id,
            exc,
        )
        return None


def maybe_advance_goal(db_url: str, goal_id: str) -> str | None:
    """Check if all steps complete; advance or reset evergreen goals.

    Returns new goal status or None if not all steps done.
    """
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)

    # Count step statuses
    rows = conn.execute(
        """
        SELECT status, COUNT(*) as cnt
        FROM goal_steps WHERE goal_id = ?
        GROUP BY status
        """,
        (goal_id,),
    ).fetchall()

    counts: dict[str, int] = {}
    for r in rows:
        counts[r["status"]] = r["cnt"]

    pending = (
        counts.get("pending", 0)
        + counts.get("running", 0)
        + counts.get("suspended", 0)
        + counts.get("waiting_approval", 0)
    )
    hard_failed = counts.get("failed", 0)
    failed = hard_failed + counts.get("blocked", 0)
    completed = counts.get("completed", 0) + counts.get("skipped", 0)

    if pending > 0:
        if hard_failed > 0:
            now_iso = _utc_now().isoformat()
            skip_message = (
                "Skipped because another step in this goal failed "
                "and the goal was closed."
            )
            skip_output = json.dumps(
                {
                    "action": "skip",
                    "reason": "goal_failed",
                }
            )

            with _db_lock:
                step_rows = conn.execute(
                    """
                    SELECT id FROM goal_steps
                    WHERE goal_id = ?
                      AND status IN (
                          'pending',
                          'running',
                          'suspended',
                          'waiting_approval'
                      )
                    """,
                    (goal_id,),
                ).fetchall()
                step_ids = [int(row["id"]) for row in step_rows]

                if step_ids:
                    placeholders = ", ".join("?" for _ in step_ids)
                    conn.execute(
                        f"""
                        UPDATE goal_steps
                        SET status = 'skipped',
                            claimed_by = NULL,
                            started_at = NULL,
                            completed_at = ?,
                            result_summary = ?,
                            output_json = ?
                        WHERE id IN ({placeholders})
                        """,
                        (now_iso, skip_message, skip_output, *step_ids),
                    )
                    conn.execute(
                        f"""
                        UPDATE action_approval_queue
                        SET status = 'expired',
                            resolved_at = ?
                        WHERE step_id IN ({placeholders})
                          AND status IN ('pending', 'approved')
                        """,
                        (now_iso, *step_ids),
                    )

                conn.execute(
                    """
                    UPDATE goal_plans
                    SET status = 'failed',
                        completed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, now_iso, goal_id),
                )
                _commit(conn)

            log.info(
                "Goal %s failed with %d residual steps; " "terminalized remaining work",
                goal_id,
                len(step_ids),
            )

            goal = conn.execute(
                "SELECT * FROM goal_plans WHERE id = ?",
                (goal_id,),
            ).fetchone()
            if not goal:
                return None
            goal = dict(goal)

            if goal.get("source") == "standing_work_order":
                try:
                    from app.services.work_orders import (
                        complete_work_order_execution,
                    )

                    complete_work_order_execution(
                        db_url=_get_db_url_from_conn(conn),
                        goal_plan_id=goal_id,
                        success=False,
                    )
                except Exception as exc:
                    log.warning(
                        "Failed to complete work order for %s: %s",
                        goal_id,
                        exc,
                    )
            return "failed"

        # Still work to do — update progress
        total = sum(counts.values())
        pct = int(completed / total * 100) if total else 0
        with _db_lock:
            conn.execute(
                """
                UPDATE goal_plans SET progress_pct = ?,
                       updated_at = ?
                WHERE id = ?
                """,
                (pct, _utc_now().isoformat(), goal_id),
            )
            _commit(conn)
        return None

    # All steps are terminal — check if evergreen
    goal = conn.execute(
        "SELECT * FROM goal_plans WHERE id = ?",
        (goal_id,),
    ).fetchone()

    if not goal:
        return None

    goal = dict(goal)
    now_iso = _utc_now().isoformat()

    if goal.get("is_evergreen") and not failed:
        # Reset all steps to pending for the next cycle
        with _db_lock:
            conn.execute(
                """
                UPDATE goal_steps
                SET status = 'pending', claimed_by = NULL,
                    started_at = NULL, completed_at = NULL,
                    result_summary = NULL, output_json = NULL,
                    attempts = 0
                WHERE goal_id = ?
                """,
                (goal_id,),
            )
            conn.execute(
                """
                UPDATE goal_plans
                SET progress_pct = 0, updated_at = ?,
                    actual_ticks = actual_ticks + 1
                WHERE id = ?
                """,
                (now_iso, goal_id),
            )
            _commit(conn)
        log.info("Evergreen goal %s reset for next cycle", goal_id)
        return "active"

    # Non-evergreen or has failures
    new_status = "completed" if not failed else "failed"
    with _db_lock:
        conn.execute(
            """
            UPDATE goal_plans
            SET status = ?, progress_pct = 100,
                completed_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_status, now_iso, now_iso, goal_id),
        )
        _commit(conn)

    # ── D016: Goal-to-task bridge — close linked task on completion ──
    if new_status == "completed":
        parent_task_id = goal.get("parent_task_id")
        if parent_task_id:
            try:
                from app.database import update_task

                closed = update_task(
                    db_url,
                    int(parent_task_id),
                    status="done",
                )
                if closed:
                    log.info(
                        "D016: Goal %s completed -> closed parent task %s",
                        goal_id,
                        parent_task_id,
                    )
                else:
                    log.warning(
                        "D016: Goal %s completed but parent task %s was not found",
                        goal_id,
                        parent_task_id,
                    )
            except Exception as exc:
                log.warning(
                    "D016: Goal %s completed but failed to close task %s: %s",
                    goal_id,
                    parent_task_id,
                    exc,
                )

    # If sourced from a work order, advance its schedule
    if goal.get("source") == "standing_work_order":
        try:
            from app.services.work_orders import (
                complete_work_order_execution,
            )

            complete_work_order_execution(
                db_url=_get_db_url_from_conn(conn),
                goal_plan_id=goal_id,
                success=(new_status == "completed"),
            )
        except Exception as exc:
            log.warning(
                "Failed to complete work order for %s: %s",
                goal_id,
                exc,
            )

    return new_status


def _get_db_url_from_conn(conn: Any) -> str:
    """Extract db_url from connection. Falls back to config."""
    try:
        from app.config import Settings

        return Settings().database_url
    except Exception:
        return "data/secretary.db"


# ── Autonomy gating ───────────────────────────────────────────────────


def _should_skip_step(
    step: dict[str, Any],
    agent_id: str,
    db_url: str,
) -> str | None:
    """Pre-flight check: can we skip this step WITHOUT calling the LLM?

    Returns a skip reason string if the step should be skipped (saving
    the LLM call), or None if the step should proceed normally.

    Checks performed (all sub-millisecond, no LLM round-trip):
      1. Required tool not in agent's department scope
      2. Required tool's integration is circuit-broken
      3. Step has exhausted retries from prior empty/failed attempts
    """
    description = step.get("description", "")
    attempts = int(step.get("attempts", 0) or 0)
    max_retries = int(step.get("max_retries", 3) or 3)

    # ── Check 1: REQUIRED TOOL not in department scope ─────────────
    required_tool = _extract_required_tool(description)
    if required_tool:
        try:
            from app.services.department_tools import is_action_allowed

            if not is_action_allowed(agent_id, required_tool):
                return (
                    f"Required tool '{required_tool}' is not in "
                    f"{agent_id}'s allowed tools — skipping LLM call"
                )
        except Exception:
            pass

    # ── Check 2: Required tool's action is circuit-broken ──────────
    if required_tool:
        try:
            from app.chat_action_resilience import _cb_is_open

            if _cb_is_open(required_tool):
                return (
                    f"Required tool '{required_tool}' is circuit-broken "
                    f"— skipping LLM call"
                )
        except Exception:
            pass

    # ── Check 3: Step already failed too many times ────────────────
    if attempts >= max_retries:
        return (
            f"Step already attempted {attempts}/{max_retries} times "
            f"— skipping LLM call"
        )

    # ── Check 4: Consecutive empty ticks on this specific step ─────
    # If the step was already attempted max_retries-1 times and the
    # error message indicates meta-only or empty patterns, don't burn
    # another call.  (Using max_retries-1 to give one last try before
    # the hard attempts-cap in Check 3.)
    skip_threshold = min(max_retries, 2)
    if attempts >= skip_threshold:
        error_msg = (step.get("error_message") or "").lower()
        if "meta-only" in error_msg or "did not complete" in error_msg:
            return (
                f"Step produced meta-only output {attempts} times "
                f"— skipping further LLM calls"
            )

    return None


def reset_blocked_required_tool_steps(
    db_url: str,
    required_tool: str,
    *,
    reason: str = "required tool recovered",
) -> int:
    """Reopen active blocked steps that depend on a repaired required tool."""
    from app.database import _db_lock, _get_conn

    tool_name = str(required_tool or "").strip()
    if not tool_name:
        return 0

    conn = _get_conn(db_url)
    note = f"Reset after {reason}."

    with _db_lock:
        cur = conn.execute(
            """
            UPDATE goal_steps
            SET status = 'pending',
                claimed_by = NULL,
                started_at = NULL,
                completed_at = NULL,
                attempts = 0,
                error_message = NULL,
                result_summary = ?,
                output_json = NULL
            WHERE status = 'blocked'
              AND description LIKE ?
              AND EXISTS (
                  SELECT 1
                  FROM goal_plans gp
                  WHERE gp.id = goal_steps.goal_id
                    AND gp.status = 'active'
              )
            """,
            (note, f"%REQUIRED TOOL: {tool_name}%"),
        )
        _commit(conn)

    if cur.rowcount:
        log.info(
            "Reset %d blocked step(s) for required tool %s",
            cur.rowcount,
            tool_name,
        )
    return int(cur.rowcount or 0)


def _extract_required_tool(description: str) -> str | None:
    """Extract the REQUIRED TOOL name from a step description, if present."""
    tools = _extract_required_tools(description)
    return tools[0] if tools else None


def _release_step_claim(db_url: str, step_id: int, reason: str) -> None:
    """Release a claimed step back to pending/blocked with a skip reason."""
    from app.database import _db_lock, _get_conn

    conn = _get_conn(db_url)
    now_iso = _utc_now().isoformat()

    with _db_lock:
        conn.execute(
            """
            UPDATE goal_steps
            SET status = 'blocked', claimed_by = NULL,
                started_at = NULL, completed_at = ?,
                error_message = ?
            WHERE id = ?
            """,
            (now_iso, reason, step_id),
        )
        _commit(conn)


def _check_autonomy(
    action_name: str,
    agent_id: str,
) -> dict[str, Any]:
    """Sub-millisecond autonomy check before tool execution.

    Returns dict with 'execute' bool and 'action' disposition.
    """
    try:
        from app.services.autonomy import should_execute

        return should_execute(action_name)
    except Exception:
        # If autonomy module unavailable, default to execute
        return {"execute": True, "level": 4, "action": "execute"}


def _policy_refusal_task_id(action_result: Any) -> str | None:
    """The approval task id carried by a POLICY_REFUSED ActionResult, if any.

    A refusal that could not queue a task returns "" -- still a refusal, but there
    is nothing for the owner to approve, so the caller must not suspend the step
    waiting on a row that does not exist.
    """
    data = getattr(action_result, "data", None)
    if not isinstance(data, dict) or not data.get("policy_refused"):
        return None
    task_id = data.get("approval_task_id")
    return str(task_id) if task_id not in (None, "") else ""


def _execute_tool_dispatch(
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str,
    *,
    goal_id: str | None = None,
) -> tuple[str, bool, str | None]:
    """Execute a tool after scope/autonomy checks have already passed.

    Returns ``(result_text, executed, policy_refusal_task_id)``. The third element
    is None for an ordinary success or an ordinary failure, and the approval task
    id (or "") when the action was refused by policy and never ran -- the caller
    uses it to tell "the tool failed" from "the gate said no".
    """

    try:
        from app.chat_actions import _dispatch_action
        from app.config import Settings

        settings = Settings()
        str_params = {
            k: str(v) if not isinstance(v, str) else v for k, v in tool_args.items()
        }
        action_result = _dispatch_action(
            tool_name,
            str_params,
            settings=settings,
            agent_id=agent_id,
        )
        result_text = str(
            getattr(action_result, "message", None)
            or getattr(action_result, "result", None)
            or getattr(action_result, "detail", None)
            or str(action_result)
        )
        action_succeeded = bool(getattr(action_result, "success", True))

        if len(result_text) > TOOL_RESULT_TRUNCATE:
            result_text = result_text[:TOOL_RESULT_TRUNCATE] + "\n...[truncated]"

        if not action_succeeded:
            # NOTE: autonomy record_failure is called inside _dispatch_action
            # (chat_action_runtime.py) for a real execution failure only.  Do NOT
            # double-count here — that caused premature L2 demotions (audit
            # 2026-03-29).  A POLICY REFUSAL returns before that call on purpose:
            # the action never ran, so it is not a failure, and this function's
            # third element carries that fact to the strike counter.
            return result_text, False, _policy_refusal_task_id(action_result)

        # Track real-world output actions for value metrics
        _track_real_output(tool_name, agent_id, settings)

        # NOTE: autonomy record_success is already called inside
        # _dispatch_action (chat_action_runtime.py).  Do NOT double-count.

        return result_text, True, None

    except Exception as exc:
        # NOTE: autonomy record_failure for exceptions is already handled
        # inside _dispatch_action.  Only log here; do not double-count.

        error_msg = f"Tool '{tool_name}' failed: {exc}"
        log.warning(
            "Agent %s tool %s failed: %s",
            agent_id,
            tool_name,
            exc,
        )
        return error_msg, False, None


def _normalize_tool_args_for_context(
    tool_name: str,
    tool_args: dict[str, Any],
    *,
    step_id: int | None,
    goal_id: str | None,
) -> dict[str, Any]:
    """Fill agent-owned workflow tool args from the current step context."""
    if tool_name != "complete_goal_step":
        return tool_args

    normalized = dict(tool_args)
    if goal_id:
        normalized["goal_id"] = goal_id
    if step_id is not None:
        normalized["step_id"] = str(step_id)
    return normalized


def _read_only_autonomy_override(
    tool_name: str,
    tool_args: dict[str, Any],
) -> dict[str, Any] | None:
    if tool_name != "ha_doors":
        return None

    action = str(tool_args.get("action") or "status").strip().lower()
    if action in {"", "status", "get", "list", "read", "show"}:
        return {
            "execute": True,
            "level": 4,
            "level_name": "L4_AUTONOMOUS",
            "action": "execute",
            "reason": "Read-only Home Assistant door status query",
        }
    return None


def _execute_tool_with_autonomy(
    tool_name: str,
    tool_args: dict[str, Any],
    agent_id: str,
    step_id: int | None = None,
    goal_id: str | None = None,
    db_url: str = "",
    bypass_autonomy: bool = False,
) -> tuple[str, bool, str | None]:
    """Execute a single tool call with autonomy gating.

    Returns (result_text, was_executed, approval_id_or_none).
    """
    from app.services.department_tools import is_action_allowed

    # Scope check: department can only use its allowed tools
    if not is_action_allowed(agent_id, tool_name):
        return (
            f"Tool '{tool_name}' is not available to {agent_id}.",
            False,
            None,
        )

    tool_args = _normalize_tool_args_for_context(
        tool_name,
        tool_args,
        step_id=step_id,
        goal_id=goal_id,
    )

    if not bypass_autonomy:
        # Autonomy check
        gate = _read_only_autonomy_override(tool_name, tool_args) or _check_autonomy(
            tool_name,
            agent_id,
        )

        if not gate.get("execute", False):
            # Queue for approval (L0-L2)
            approval_id = _queue_for_approval(
                agent_id=agent_id,
                step_id=step_id,
                goal_id=goal_id,
                tool_name=tool_name,
                arguments=tool_args,
                autonomy_level=gate.get("level", 0),
                db_url=db_url,
            )
            disposition = gate.get("action", "request_approval")
            msg = (
                f"Action '{tool_name}' requires approval "
                f"(level {gate.get('level', 0)}, {disposition}). "
                f"Queued as approval #{approval_id}."
            )
            return msg, False, approval_id

    result_text, executed, refusal_task_id = _execute_tool_dispatch(
        tool_name,
        tool_args,
        agent_id,
        goal_id=goal_id,
    )
    # FU9: the one site that can tell "the tool ran and failed" from "the tool was
    # never allowed to run". A scope refusal (:2030) and an approval queueing
    # (:2051) both return *before* this point, so neither is counted as a failure
    # of the tool; and a success clears the counters, which is the loop's first
    # exit condition.
    if executed:
        _clear_tool_failures_for(agent_id, tool_name)
    elif refusal_task_id is not None:
        # ── POLICY REFUSAL (2026-10-26) ──
        # The gate refused this deliberately: the action never ran, so this is not a
        # failure of the tool and must not count a strike. Three identical refusals
        # used to fire TOOL_LOOP_DEADLOCK and end the step having done nothing (the
        # security department's whole mission), and the step was reported as broken
        # when it was only waiting. Returning the approval task id takes the
        # caller's existing "approval needed" path, so the step suspends as
        # waiting-on-owner and the refusal is visible as a decision.
        #
        # `is not None` rather than truthiness on purpose: "" means "refused, and no
        # approval task could be written" (measured 2026-10-26: the company sat at
        # its 300-task ceiling, so this branch is live). That is still a refusal and
        # must not count a strike; it returns None as the approval id because there
        # is no row for the step to suspend on.
        return result_text, False, (refusal_task_id or None)
    else:
        _note_tool_failure(agent_id, tool_name, result_text)
    return result_text, executed, None


def _queue_for_approval(
    agent_id: str,
    step_id: int | None,
    goal_id: str | None,
    tool_name: str,
    arguments: dict[str, Any],
    autonomy_level: int = 0,
    db_url: str = "",
) -> str:
    """Insert a pending action into the approval queue.

    Returns the approval ID.
    """
    approval_id = uuid.uuid4().hex[:12]
    try:
        from app.database import _db_lock, _get_conn

        conn = _get_conn(db_url)
        now_iso = _utc_now().isoformat()

        with _db_lock:
            conn.execute(
                """INSERT INTO action_approval_queue
                   (id, agent_id, step_id, goal_id, tool_name,
                    arguments, autonomy_level, status, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', ?)""",
                (
                    approval_id,
                    agent_id,
                    step_id,
                    goal_id,
                    tool_name,
                    json.dumps(arguments),
                    autonomy_level,
                    now_iso,
                ),
            )
            _commit(conn)
    except Exception as exc:
        log.error("Failed to queue approval: %s", exc)

    return approval_id


# ── Multi-turn tool execution ─────────────────────────────────────────


def _execute_llm_step(
    messages: list[dict[str, str]],
    tools: list[dict[str, Any]] | None = None,
    agent_id: str = "",
    step_id: int | None = None,
    goal_id: str | None = None,
    db_url: str = "",
) -> StepResult:
    """Execute a step with multi-turn tool calling (max 3 rounds).

    Uses structured tool calling via copilot_chat with real tool
    dispatch through chat_actions, gated by autonomy checks.
    """
    total_tokens_in = 0
    total_tokens_out = 0
    tools_used: list[str] = []
    tools_executed: list[str] = []  # Only successfully dispatched tools
    tool_call_details: list[dict[str, Any]] = []  # Rich records for telemetry
    approval_ids: list[str] = []
    has_tools = bool(tools)
    current_messages = list(messages)
    # ── PROMPT-SHAPE diagnostic (2026-10-20) ──
    # One line per step, only when AGENT_LOG_PROMPT_SHAPE is set. Logs role and CHARACTER COUNT per message,
    # never the content. It exists to answer a question the numbers alone could not: what fills a 45k-token
    # prompt when the identifiable parts sum to under 10k. Remove once answered.
    import os as _shape_os  # local: this module has no top-level `import os`

    if _shape_os.environ.get("AGENT_LOG_PROMPT_SHAPE", "").strip().lower() in ("1", "true", "yes", "on"):
        try:
            _parts = []
            _total = 0
            for _m in current_messages:
                _content = _m.get("content")
                _n = len(_content) if isinstance(_content, str) else len(str(_content or ""))
                _total += _n
                _parts.append(f"{_m.get('role')}:{_n}")
            log.warning(
                "PROMPT-SHAPE agent=%s msgs=%d total_chars=%d approx_tokens=%d parts=%s",
                agent_id,
                len(current_messages),
                _total,
                _total // 4,
                ",".join(_parts),
            )
        except Exception:  # noqa: BLE001 - diagnostics must never break a step
            log.exception("PROMPT-SHAPE logging failed")
    prompt_text = "\n".join(
        str(message.get("content", ""))
        for message in messages
        if isinstance(message, dict)
    )
    required_tools = _extract_required_tools(prompt_text)
    # 2026-10-02: a REQUIRED TOOL this host cannot run must not be enforced.
    # Enforcing it makes the gate below refuse every other tool ("This step
    # requires one of these tools first: browser_use_run") while the required
    # tool itself can only answer "not installed" -- a step with no legal move.
    # Drop it from the requirement and say so; the step then runs on the tools
    # the host actually has.
    if required_tools:
        _unusable_required: list[str] = []
        try:
            from app.services.department_tools import (
                tool_runtime_unavailable_reason,
            )

            for _name in required_tools:
                _why = tool_runtime_unavailable_reason(_name)
                if _why:
                    _unusable_required.append(f"{_name} ({_why})")
        except Exception:  # noqa: BLE001 - never break a step over this check
            pass
        if _unusable_required:
            _unusable_names = {
                entry.split(" ", 1)[0] for entry in _unusable_required
            }
            required_tools = [
                t for t in required_tools if t not in _unusable_names
            ]
            log.warning(
                "Agent %s step %s: dropping uncallable required tool(s) from the "
                "step contract: %s",
                agent_id,
                step_id,
                "; ".join(_unusable_required),
            )
    route_contract = _extract_route_contract(prompt_text)
    fallback_policy = _department_copilot_fallback_policy(
        messages=messages,
        agent_id=agent_id,
        required_tools=required_tools,
        has_tools=has_tools,
        contract=route_contract,
    )
    dept_models = _available_department_models()
    # A step may pin a route alias in its own ROUTE CONTRACT. The alias is the
    # gateway's own id, so it goes first verbatim -- the catalogue is what has
    # to list it, and the alias is the thing that is re-pointed when models
    # change, which is the whole point of pinning one.
    if route_contract.public_alias in _ALLOWED_ROUTE_ALIASES:
        pinned = route_contract.public_alias
        dept_models = [pinned] + [m for m in dept_models if m != pinned]
    if route_contract.public_alias == "secretary-fast":
        # Fast lane: exactly one candidate, decided by the gateway's own
        # `secretary-fast` policy. No local model list competes with it.
        dept_models = dept_models[:1]
    active_model = dept_models[0]
    # Per-tick action counter — persists across all LLM rounds so the
    # limit is enforced per tick, not per round.
    _tick_action_counts: dict[str, int] = {}

    # ── Cognitive routing: decide System 1 vs 2 and log decision ──
    cognitive_system: int = 1
    cognitive_confidence: float | None = None
    log_cognitive_decision_fn = None
    try:
        from app.services.cognitive_router import (
            decide_system,
            log_cognitive_decision,
        )

        log_cognitive_decision_fn = log_cognitive_decision

        step_desc = ""
        if messages:
            last_user = [m for m in messages if m.get("role") == "user"]
            if last_user:
                step_desc = last_user[-1].get("content", "")[:200]
        routing = decide_system(
            agent_id=agent_id,
            task_type=step_desc[:50] if step_desc else None,
            complexity="medium",
            context_tokens=sum(len(m.get("content", "")) // 4 for m in messages),
        )
        cognitive_system = routing.get("system", 1)
    except Exception:
        pass

    def _finalize_step(result: StepResult, *, outcome: str) -> StepResult:
        if log_cognitive_decision_fn is not None:
            try:
                log_cognitive_decision_fn(
                    agent_id=agent_id,
                    system_used=cognitive_system,
                    initial_confidence=None,
                    final_confidence=cognitive_confidence,
                    retries=0,
                    escalated=(cognitive_system == 2),
                    task_type="agent_step",
                    outcome=outcome,
                    cost_usd=_estimate_cost(
                        total_tokens_in,
                        total_tokens_out,
                        active_model,
                    ),
                )
            except Exception:
                pass
        return result

    def _tool_loop_stop(
        tool_name: str,
        state: dict[str, Any],
        *,
        called: bool,
    ) -> StepResult:
        """End the step on the named tool-loop verdict. The exit, in one place.

        Returns rather than raises: the caller of `_execute_llm_step` catches broad
        exceptions, so a raise would lose the verdict text. `tool_rounds` reports
        the round the loop actually reached, and the refused call is recorded in
        `tool_call_details` so an operator sees the stop in telemetry and not only
        in prose.
        """
        verdict = _tool_loop_deadlock_summary(
            agent_id, tool_name, state, called=called
        )
        log.error(
            "Agent %s step %s tool-loop deadlock: %s", agent_id, step_id, verdict
        )
        tool_call_details.append(
            {
                "name": tool_name,
                "executed": False,
                "args": {},
                "result": verdict[:1200],
                "error": True,
                "approval_id": None,
                "tool_loop_deadlock": True,
                "strikes": int(state.get("strikes") or 0),
                "repeat_limit": _tool_deadlock_limits()[0],
                "failure_class": str(state.get("failure_class") or ""),
            }
        )
        return _finalize_step(
            StepResult(
                action="error",
                result_summary=verdict,
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost_usd=_estimate_cost(
                    total_tokens_in,
                    total_tokens_out,
                    active_model,
                ),
                tools_used=tools_used,
                tools_executed=tools_executed,
                tool_call_details=tool_call_details,
                tool_rounds=round_num + 1,
            ),
            outcome="tool_loop_deadlock",
        )

    max_rounds = route_contract.max_retries or MAX_TOOL_ROUNDS
    if not has_tools:
        max_rounds = 1
    if route_contract.require_json_output:
        current_messages.append(
            {
                "role": "user",
                "content": "Return the final answer as compact JSON when no tool call is needed.",
            }
        )

    # ── Closed-loop exit (checked before any provider call) ────────────
    # If this agent has already failed identically, on one of the models in this
    # chain, past the limit inside the window, stop here: no Copilot attempt, no
    # gateway fallback, no money. The state change is the point — the August
    # outage had none, so every tick re-entered this function with inputs just
    # as doomed.
    _deadlock_limit, _deadlock_window = _llm_deadlock_limits()
    _model_strikes = _max_model_strikes(agent_id, dept_models)
    if _model_strikes >= _deadlock_limit:
        _exit_condition = _llm_deadlock_exit_condition(agent_id)
        _record_llm_outage(
            "agent_llm_deadlock",
            agent_id=agent_id,
            step_id=step_id,
            goal_id=goal_id,
            model_chain=list(dept_models),
            strike_count=_model_strikes,
            repeat_limit=_deadlock_limit,
            window_sec=_deadlock_window,
            exit_condition=_exit_condition,
        )
        log.error(
            "Agent %s step %s quarantined: one model in the chain %s has failed "
            "identically %s times inside %.0fs - refusing another doomed attempt. "
            "%s.",
            agent_id,
            step_id,
            list(dept_models),
            _model_strikes,
            _deadlock_window,
            _exit_condition,
        )
        return _finalize_step(
            StepResult(
                action="error",
                result_summary=(
                    "LLM deadlock: 0 provider calls attempted - the department "
                    f"model chain {list(dept_models)} has failed identically "
                    f"{_model_strikes} times in the last {_deadlock_window:.0f}s, "
                    "so another attempt is guaranteed to fail the same way and is "
                    f"not made ({_exit_condition})."
                ),
                tokens_in=total_tokens_in,
                tokens_out=total_tokens_out,
                cost_usd=0.0,
                tools_used=tools_used,
                tools_executed=tools_executed,
                tool_call_details=tool_call_details,
                tool_rounds=0,
            ),
            outcome="failure",
        )

    for round_num in range(max_rounds):
        # ── Context pruning (2026-10-20) ──
        # Every round re-sends the whole accumulated message list, and each tool result may be
        # TOOL_RESULT_TRUNCATE (12,000) characters. Measured: prompts run 27k-43k tokens around a
        # ~700-token stable head, so the provider prefix cache hits 0.86 % here while the owner sees
        # 99.9 % in interactive sessions. This keeps the LATEST round at full fidelity - that is what the
        # model acts on - and stubs the older tool results. INERT BY DEFAULT: AGENT_ELIDE_OLD_TOOLS must
        # be set, so this deploy changes nothing until an operator turns it on.
        import os as _os  # local: this module has no top-level `import os`

        if _os.environ.get("AGENT_ELIDE_OLD_TOOLS", "0").strip().lower() in ("1", "true", "yes", "on"):
            try:
                from app.services.context_pruning import elide_old_tool_results

                current_messages, _pruned_chars = elide_old_tool_results(
                    current_messages, keep_last_rounds=1
                )
            except Exception:  # noqa: BLE001 - a cost optimisation must never fail a tick
                log.exception("agent_worker: context pruning failed; sending the full history")
        round_errors: list[str] = []
        try:
            from app.copilot_client import (
                copilot_chat,
                copilot_quota_exhausted,
                copilot_rate_limit_circuit_open,
            )

            reply_text = ""
            usage: dict[str, Any] = {}
            tool_calls: list[dict[str, Any]] = []
            request_succeeded = False

            # When a step has REQUIRED TOOL and it hasn't been
            # executed yet, narrow the tool schemas so the LLM only
            # sees the required tool(s) + lookup helpers.  Once the
            # required tool is executed, expand back to the full set.
            effective_tools = tools
            if (
                required_tools
                and not any(t in tools_executed for t in required_tools)
                and tools
            ):
                _allowed = frozenset(required_tools) | _LOOKUP_TOOLS_ALWAYS_ALLOWED
                effective_tools = [
                    t
                    for t in tools
                    if (t.get("function", {}).get("name", "") in _allowed)
                ]
                if not effective_tools:
                    effective_tools = tools  # fallback to full set

            for dept_model in list(dept_models):
                if copilot_rate_limit_circuit_open():
                    # Hourly 429 circuit tripped — skip Copilot entirely
                    # and go straight to the gateway fallback below.
                    round_errors.append(
                        "copilot 429 circuit open; skipping copilot tier"
                    )
                    log.warning(
                        "Agent %s step %s round %s skipping Copilot: "
                        "429 circuit open",
                        agent_id,
                        step_id,
                        round_num + 1,
                    )
                    break
                if copilot_quota_exhausted():
                    # Monthly 402 quota exhausted — skip Copilot entirely
                    # and go straight to the gateway fallback below.
                    round_errors.append(
                        "copilot 402 quota exhausted; skipping copilot tier"
                    )
                    log.warning(
                        "Agent %s step %s round %s skipping Copilot: "
                        "402 quota exhausted",
                        agent_id,
                        step_id,
                        round_num + 1,
                    )
                    break
                # ── Skip Copilot for non-Copilot models ──────────────
                # DEPT_MODEL_CANDIDATES may contain direct-provider
                # models (e.g. deepseek/deepseek-v4-flash) that Copilot
                # doesn't support.  Don't waste a round — go straight to
                # the gateway fallback.
                from app.copilot_client import COPILOT_MODELS

                if dept_model not in COPILOT_MODELS:
                    round_errors.append(
                        f"{dept_model} not in Copilot roster; skipping to gateway"
                    )
                    log.info(
                        "Agent %s step %s round %s: %s not in COPILOT_MODELS — "
                        "using gateway fallback",
                        agent_id, step_id, round_num + 1, dept_model,
                    )
                    break
                attempt_started = time.monotonic()
                try:
                    if has_tools:
                        reply_text, usage, tool_calls = copilot_chat(
                            model=dept_model,
                            messages=current_messages,
                            max_tokens=MAX_OUTPUT_TOKENS,
                            temperature=0.1,
                            tools=effective_tools,
                            tool_choice="auto",
                        )
                    else:
                        # Fallback to text-only (no tools available)
                        reply_text, usage, tool_calls = copilot_chat(
                            model=dept_model,
                            messages=current_messages,
                            max_tokens=MAX_OUTPUT_TOKENS,
                            temperature=0.1,
                        )
                    _log_llm_usage(
                        db_url=db_url,
                        agent_id=agent_id,
                        model=dept_model,
                        usage=usage,
                        latency_ms=int((time.monotonic() - attempt_started) * 1000),
                        success=True,
                    )
                    active_model = dept_model
                    request_succeeded = True
                    # A real success is the first exit from the loop: forget the
                    # counters for this agent so a blip is never quarantined by
                    # failures that happened before it recovered.
                    _clear_llm_failures_for(agent_id)
                    if dept_models[0] != dept_model:
                        remaining_models = [
                            model for model in dept_models if model != dept_model
                        ]
                        dept_models = [
                            dept_model,
                            *remaining_models,
                        ]
                        log.warning(
                            "Agent %s step %s round %s fell back to model %s",
                            agent_id,
                            step_id,
                            round_num + 1,
                            dept_model,
                        )
                    break
                except ImportError:
                    raise
                except Exception as exc:
                    error_text = str(exc).strip() or exc.__class__.__name__
                    _log_llm_usage(
                        db_url=db_url,
                        agent_id=agent_id,
                        model=dept_model,
                        usage=None,
                        latency_ms=int((time.monotonic() - attempt_started) * 1000),
                        success=False,
                        error_message=error_text,
                    )
                    round_errors.append(f"{dept_model}: {error_text}")
                    # Count the identical failure. The key excludes the step and
                    # the clock, so a rebuilt step that fails the same way is the
                    # same failure - which is exactly the six-day shape.
                    _llm_error_class = _llm_failure_class(error_text)
                    _llm_signature = _llm_failure_signature(
                        agent_id, dept_models, error_text, model=dept_model
                    )
                    _llm_strikes = _note_llm_failure(_llm_signature)
                    _llm_limit, _llm_window = _llm_deadlock_limits()
                    _record_llm_outage(
                        "agent_llm_failure",
                        agent_id=agent_id,
                        step_id=step_id,
                        model=dept_model,
                        model_chain=list(dept_models),
                        strike_count=_llm_strikes,
                        repeat_limit=_llm_limit,
                        window_sec=_llm_window,
                        failure_class=_llm_error_class,
                        exit_condition=_llm_deadlock_exit_condition(agent_id),
                    )
                    if _llm_strikes >= _llm_limit:
                        log.error(
                            "Agent %s step %s model %s has failed identically %s "
                            "times inside %.0fs (failure_class=%s) - the next "
                            "attempt will be quarantined. %s.",
                            agent_id,
                            step_id,
                            dept_model,
                            _llm_strikes,
                            _llm_window,
                            _llm_error_class,
                            _llm_deadlock_exit_condition(agent_id),
                        )
                        # Record the transition the moment the limit is crossed,
                        # not only on the next (quarantined) attempt: a monitor
                        # polling less often than the tick interval would
                        # otherwise miss that this loop became a deadlock at all.
                        _record_llm_outage(
                            "agent_llm_deadlock",
                            agent_id=agent_id,
                            step_id=step_id,
                            model=dept_model,
                            model_chain=list(dept_models),
                            strike_count=_llm_strikes,
                            repeat_limit=_llm_limit,
                            window_sec=_llm_window,
                            failure_class=_llm_error_class,
                            exit_condition=_llm_deadlock_exit_condition(agent_id),
                        )
                    log.warning(
                        "Agent %s step %s round %s model %s failed: %s",
                        agent_id,
                        step_id,
                        round_num + 1,
                        dept_model,
                        error_text,
                    )
                    if "status 429" in error_text:
                        # All department models share the same Copilot
                        # quota — sibling models will 429 too.  Stop
                        # burning calls and use the gateway fallback.
                        round_errors.append(
                            "copilot rate limited; skipping sibling models"
                        )
                        break

            # ── Gateway fallback (doc 19 §3.2) ──
            # On Copilot rate limiting (or any total Copilot failure),
            # route through the AI gateway using a direct provider pin
            # (bypassing meta-model smart routing) so the original model
            # (e.g. deepseek/deepseek-v4-flash) is used directly instead
            # of being routed through the secretary-fast meta-model chain
            # that can cascade to incompatible providers (e.g. x.ai).
            # The gateway applies its own budget gating, so this cannot
            # bypass cost controls.
            if not request_succeeded:
                # The chain's ids are gateway ids already (route aliases, or
                # catalogue-validated canonical ids). A legacy short id is
                # translated; a route alias passes through AS ITSELF, because
                # rewriting `secretary-smart` to `secretary-fast` here is what
                # silently downgraded every pinned step.
                _gateway_model = (
                    dept_model
                    if dept_model in _ALLOWED_ROUTE_ALIASES
                    else SHORT_TO_CANONICAL_MODEL.get(dept_model, dept_model)
                )
                if not _gateway_model:
                    _gateway_model = "secretary-fast"
                attempt_started = time.monotonic()
                try:
                    gw_reply, gw_usage, gw_tool_calls, gw_model = (
                        _call_department_gateway_chat(
                            model=_gateway_model,
                            messages=current_messages,
                            max_tokens=MAX_OUTPUT_TOKENS,
                            temperature=0.1,
                            tools=effective_tools if has_tools else None,
                            tool_choice="auto" if has_tools else None,
                            agent_id=agent_id or "dept_worker",
                            budget_tier=route_contract.budget_tier,
                        )
                    )
                    reply_text, usage, tool_calls = gw_reply, gw_usage, gw_tool_calls
                    active_model = gw_model
                    request_succeeded = True
                    # Second and last exit from the loop: a gateway recovery is a
                    # real success and clears the counters.
                    _clear_llm_failures_for(agent_id)
                    log.warning(
                        "Agent %s step %s round %s recovered via gateway "
                        "fallback model %s",
                        agent_id,
                        step_id,
                        round_num + 1,
                        gw_model,
                    )
                except Exception as exc:
                    error_text = str(exc).strip() or exc.__class__.__name__
                    round_errors.append(f"gateway-fallback: {error_text}")
                    # The gateway refusal is the same loop as the Copilot
                    # failure, not a separate one: a dead model id *plus* a
                    # budget-blocked fallback is one closed loop, and counting
                    # them separately would let each half stay under the limit
                    # forever — which is what August did.
                    _gw_strikes = _note_llm_failure(
                        _llm_failure_signature(
                            agent_id, dept_models, error_text, model=_gateway_model
                        )
                    )
                    _record_llm_outage(
                        "agent_llm_failure",
                        agent_id=agent_id,
                        step_id=step_id,
                        model=_gateway_model,
                        model_chain=list(dept_models),
                        lane="gateway",
                        strike_count=_gw_strikes,
                        repeat_limit=_llm_deadlock_limits()[0],
                        window_sec=_llm_deadlock_limits()[1],
                        failure_class=_llm_failure_class(error_text),
                        exit_condition=_llm_deadlock_exit_condition(agent_id),
                    )
                    log.warning(
                        "Agent %s step %s round %s gateway fallback failed: %s",
                        agent_id,
                        step_id,
                        round_num + 1,
                        error_text,
                    )

            if not request_succeeded:
                summary = "; ".join(round_errors)[:600] or "unknown LLM failure"
                if not fallback_policy.allow_copilot:
                    summary = f"Fallback blocked ({fallback_policy.reason}): {summary}"
                # Carry the loop's own state into the operator-visible text.
                # Without this the summary is only today's two errors; with it,
                # a reader sees the chain that is dead, the strike count, and how
                # to clear it - which is what the August outage never showed.
                _chain_strikes_now = note_model_chain_strikes(agent_id, dept_models)
                if _chain_strikes_now:
                    # Prepend, never truncate: the loop's own state and the exit
                    # condition must be the first thing a reader sees, and the
                    # original errors must survive intact behind them. The count
                    # reported is the *chain* count — the ticks this agent has
                    # spent failing on this chain — because that is the cadence
                    # the tick loop repeats at.
                    _llm_limit_now, _llm_window_now = _llm_deadlock_limits()
                    summary = (
                        "[identical failure "
                        f"{_chain_strikes_now}/{_llm_limit_now} for this model chain "
                        f"inside {_llm_window_now:.0f}s] "
                        f"{_llm_deadlock_exit_condition(agent_id)} | {summary}"
                    )
                return _finalize_step(
                    StepResult(
                        action="error",
                        result_summary=(
                            f"LLM error (round {round_num + 1}): {summary}"
                        ),
                        tokens_in=total_tokens_in,
                        tokens_out=total_tokens_out,
                        cost_usd=_estimate_cost(
                            total_tokens_in,
                            total_tokens_out,
                            active_model,
                        ),
                        tools_used=tools_used,
                        tools_executed=tools_executed,
                        tool_call_details=tool_call_details,
                        tool_rounds=round_num + 1,
                    ),
                    outcome="failure",
                )

            t_in = usage.get("prompt_tokens", 0)
            t_out = usage.get("completion_tokens", 0)
            total_tokens_in += t_in
            total_tokens_out += t_out

            # If tools were available and the model answered in text on the
            # first round, retry once in the same tick before burning another
            # scheduled worker cycle.
            if has_tools and not tool_calls and round_num == 0:
                current_messages.append(
                    {
                        "role": "assistant",
                        "content": reply_text or "I responded without a tool call.",
                    }
                )
                current_messages.append(
                    {
                        "role": "user",
                        "content": (
                            "You returned text only. You MUST use a tool call "
                            "to do the work for this step. Do not respond in "
                            "plain text unless a tool result proves the step is done."
                        ),
                    }
                )
                continue

            # If no tool calls, this is the final response
            if not tool_calls:
                result = _parse_final_response(
                    reply_text,
                    total_tokens_in,
                    total_tokens_out,
                    tools_used,
                    round_num + 1,
                    approval_ids,
                    active_model,
                    tools_executed=tools_executed,
                    tool_call_details=tool_call_details,
                )
                final_outcome = (
                    "success" if result.action == "complete" else result.action
                )
                return _finalize_step(result, outcome=final_outcome)

            # Process each tool call
            any_approval_needed = False
            for tc in tool_calls:
                # 2026-08-30: coerce to str — gateway can return name:null
                # and None poisons tools_used joins downstream.
                tc_name = str(tc.get("name") or "")
                tc_args = tc.get("args", {})
                if isinstance(tc_args, str):
                    try:
                        tc_args = json.loads(tc_args)
                    except Exception:
                        tc_args = {}

                tools_used.append(tc_name)

                if (
                    required_tools
                    and not tools_executed
                    and tc_name not in required_tools
                    and tc_name not in _LOOKUP_TOOLS_ALWAYS_ALLOWED
                ):
                    result_text = (
                        "This step requires one of these tools first: "
                        f"{', '.join(required_tools)}. "
                        f"Do not call {tc_name} before satisfying "
                        "that requirement."
                    )
                    executed = False
                    appr_id = None
                else:
                    missing_fields = _missing_required_tool_fields(
                        tc_name,
                        tc_args,
                        tools,
                    )
                    if missing_fields:
                        result_text = (
                            f"Invalid {tc_name} call: missing required fields "
                            f"{', '.join(missing_fields)}."
                        )
                        if tc_name == "repo_run_command":
                            result_text += (
                                " Provide repo_path using a department "
                                "repo alias and a non-empty command."
                            )
                        executed = False
                        appr_id = None
                    else:
                        # Per-action-per-step rate limit to prevent
                        # runaway loops. Read-only tools get a higher ceiling than
                        # mutating ones - see _PER_TICK_ACTION_LIMIT above.
                        _tick_action_counts[tc_name] = (
                            _tick_action_counts.get(tc_name, 0) + 1
                        )
                        _limit = (
                            _PER_TICK_LOOKUP_ACTION_LIMIT
                            if tc_name in _LOOKUP_TOOLS_ALWAYS_ALLOWED
                            else _PER_TICK_ACTION_LIMIT
                        )
                        if _tick_action_counts[tc_name] > _limit:
                            result_text = (
                                f"Rate limit: {tc_name} called "
                                f"{_tick_action_counts[tc_name]}x "
                                f"this step (limit {_limit}). "
                                "Finish this step with what you have and continue "
                                "in the next step."
                            )
                            executed = False
                            appr_id = None
                            log.warning(
                                "Per-tick rate limit hit: %s called %dx by %s",
                                tc_name,
                                _tick_action_counts[tc_name],
                                agent_id,
                            )
                        else:
                            # ── Tool-loop exit (checked before the tool is called) ──
                            # Same shape as the LLM deadlock check at the top of this
                            # function: if this tool has already failed identically
                            # past its limit inside the window, do not call it again,
                            # and do not spend another round discovering that. The
                            # state change is the point -- FU9's session re-issued
                            # `upgrade_tool` after its own failure and spent the rest
                            # of its wall clock redoing the same two tool calls.
                            _tool_state = _tool_deadlock_state(agent_id, tc_name)
                            if (
                                int(_tool_state.get("strikes") or 0)
                                >= _tool_deadlock_limits()[0]
                            ):
                                return _tool_loop_stop(
                                    tc_name, _tool_state, called=False
                                )
                            result_text, executed, appr_id = (
                                _execute_tool_with_autonomy(
                                    tool_name=tc_name,
                                    tool_args=tc_args,
                                    agent_id=agent_id,
                                    step_id=step_id,
                                    goal_id=goal_id,
                                    db_url=db_url,
                                )
                            )
                            if not executed and not appr_id:
                                # ── Reached the limit: this is the loop's exit ──
                                # `_execute_tool_with_autonomy` counted this failure
                                # at the site that decides it. If this was the
                                # identical repeat that crossed the limit, stop the
                                # step here rather than spending the remaining rounds
                                # re-issuing a call that has just proved it fails the
                                # same way. The verdict names the class and the text
                                # of *this* failure, not of some earlier one.
                                _strikes = _tool_deadlock_open(
                                    _tool_failure_signature(
                                        agent_id, tc_name, result_text
                                    )
                                )
                                if _strikes >= _tool_deadlock_limits()[0]:
                                    return _tool_loop_stop(
                                        tc_name,
                                        {
                                            "strikes": _strikes,
                                            "failure_class": _tool_failure_class(
                                                result_text
                                            ),
                                            "last_error": str(result_text or ""),
                                        },
                                        called=True,
                                    )

                                # 2026-09-04: an approval_id means the autonomy gate
                # queued this action for owner approval. Mark the step as
                # needing suspension and record the approval id so the
                # caller can route it. Previously this was never set, so
                # 'approval needed' silently looked complete.
                if appr_id:
                    any_approval_needed = True
                    approval_ids.append(appr_id)
                if executed:
                    tools_executed.append(tc_name)
            # Capture the tool outcome for telemetry. result_text holds the
            # model-visible result (success text, denial reason, rate-limit
            # note, or approval-required). Truncate the stored preview so the
            # telemetry column stays small while still showing what happened.
            _stub = str(result_text or "")
            tool_call_details.append(
                {
                    "name": tc_name,
                    "executed": executed,
                    "args": dict(tc_args) if isinstance(tc_args, dict) else {},
                    "result": _stub[:1200],
                    "error": bool(executed in (False, None) and _stub),
                    "approval_id": appr_id,
                }
            )

            # Append tool result to messages for next round
            current_messages.append(
                {
                    "role": "assistant",
                    "content": (
                        f"Called {tc_name}(" f"{json.dumps(tc_args)[:200]})"
                    ),
                }
            )
            current_messages.append(
                {
                    "role": "user",
                    "content": (f"Tool result for {tc_name}:\n" f"{result_text}"),
                }
            )

            # If approval needed, suspend the step
            if any_approval_needed:
                return _finalize_step(
                    StepResult(
                        action="suspended",
                        result_summary=(
                            "Step suspended — awaiting approval for: "
                            + ", ".join(
                                str(tc.get("name") or "?") for tc in tool_calls
                            )
                        ),
                        tokens_in=total_tokens_in,
                        tokens_out=total_tokens_out,
                        cost_usd=_estimate_cost(
                            total_tokens_in,
                            total_tokens_out,
                            active_model,
                        ),
                        tools_used=tools_used,
                        tools_executed=tools_executed,
                        tool_call_details=tool_call_details,
                        tool_rounds=round_num + 1,
                        approval_ids=approval_ids,
                    ),
                    outcome="approval_pending",
                )

        except ImportError:
            log.warning("copilot_client not available for agent work")
            return _finalize_step(
                StepResult(
                    action="complete",
                    result_summary=("Step acknowledged (no LLM available)"),
                ),
                outcome="no_llm",
            )
        except Exception as exc:
            return _finalize_step(
                StepResult(
                    action="error",
                    result_summary=f"LLM error (round {round_num + 1}): {exc}",
                    tokens_in=total_tokens_in,
                    tokens_out=total_tokens_out,
                    cost_usd=_estimate_cost(
                        total_tokens_in,
                        total_tokens_out,
                        active_model,
                    ),
                    tools_used=tools_used,
                    tools_executed=tools_executed,
                    tool_call_details=tool_call_details,
                    tool_rounds=round_num + 1,
                ),
                outcome="failure",
            )

    # Exhausted all rounds — return what we have
    return _finalize_step(
        StepResult(
            action="complete",
            result_summary=(
                f"Completed after {max_rounds} tool rounds. "
                f"Tools used: {', '.join(str(t) for t in tools_used) or 'none'}."
            ),
            tokens_in=total_tokens_in,
            tokens_out=total_tokens_out,
            cost_usd=_estimate_cost(
                total_tokens_in,
                total_tokens_out,
                active_model,
            ),
            tools_used=tools_used,
            tools_executed=tools_executed,
            tool_call_details=tool_call_details,
            tool_rounds=max_rounds,
        ),
        outcome=("success" if tools_executed else "no_tools"),
    )


def _parse_final_response(
    reply_text: str,
    tokens_in: int,
    tokens_out: int,
    tools_used: list[str],
    tool_rounds: int,
    approval_ids: list[str],
    model: str = "",
    tools_executed: list[str] | None = None,
    tool_call_details: list[dict[str, Any]] | None = None,
) -> StepResult:
    """Parse the final LLM text response into a StepResult."""
    _exec = tools_executed or []
    _details = tool_call_details or []

    # Try JSON parse first (legacy format)
    try:
        parsed = json.loads(reply_text)
        if isinstance(parsed, dict):
            return StepResult(
                action=parsed.get("action", "complete"),
                result_summary=parsed.get("result_summary", reply_text[:500]),
                next_step_context=parsed.get("next_step_context"),
                tokens_in=tokens_in,
                tokens_out=tokens_out,
                cost_usd=_estimate_cost(tokens_in, tokens_out, model),
                tools_used=tools_used,
                tools_executed=_exec,
                tool_call_details=_details,
                tool_rounds=tool_rounds,
                approval_ids=approval_ids,
            )
    except (json.JSONDecodeError, TypeError):
        pass

    # Plain text response — treat as completion summary
    return StepResult(
        action="complete",
        result_summary=reply_text[:500] if reply_text else "Done.",
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        cost_usd=_estimate_cost(tokens_in, tokens_out, model),
        tools_used=tools_used,
        tools_executed=_exec,
        tool_call_details=_details,
        tool_rounds=tool_rounds,
        approval_ids=approval_ids,
    )


def _dept_model_env_chain() -> list[str]:
    """Operator-configured model ids, comma-separated, in precedence order."""
    import os

    chain: list[str] = []
    for var in DEPT_MODEL_ENV_CHAIN:
        raw = (os.environ.get(var) or "").strip()
        if not raw:
            continue
        for part in raw.split(","):
            model_id = part.strip()
            if model_id and model_id not in chain:
                chain.append(model_id)
    return chain


def _dept_model_catalogue():
    """The live gateway catalogue, or None when it cannot be read.

    `smart_router.gateway_catalogue()` is the same source `GET /v1/models`
    serves: it fetches the gateway's own list, caches it under its own TTL, and
    never raises (a failure keeps the last good list and records the error on
    the snapshot). Fail-soft is therefore already its contract -- this wrapper
    only has to survive an import failure.
    """
    try:
        from app.services.smart_router import gateway_catalogue

        return gateway_catalogue()
    except Exception as exc:  # noqa: BLE001 - resolution must never raise
        log.warning("Department model resolution: gateway catalogue unavailable: %s", exc)
        return None


def _resolve_department_models() -> tuple[list[str], str]:
    """Build the department model chain: (chain, source).

    Precedence, then validation, exactly as the standing rule requires:
      1. operator env override (`SECRETARY_DEPT_MODEL`, ...) -- comma chain;
      2. the route aliases in `DEPT_MODEL_CANDIDATES` that the catalogue lists;
      3. the model registry's non-copilot tiers, for compatibility;
    and the catalogue is the gate on ALL of them: every id that the live
    catalogue does not list is dropped with a warning, so a configured id that
    stopped existing can never be pinned silently again.
    """
    catalogue = _dept_model_catalogue()
    listed = getattr(catalogue, "ids", None)
    dropped: list[str] = []

    def _keep(ids: list[str]) -> list[str]:
        if listed is None:
            # Catalogue unknown: we cannot validate, so we do not pretend to.
            return list(ids)
        out: list[str] = []
        for model_id in ids:
            if model_id in listed:
                out.append(model_id)
            else:
                dropped.append(model_id)
        return out

    alias_ids = [a for a in DEPT_ROUTE_ALIASES]
    env_ids = _keep(_dept_model_env_chain())
    alias_kept = _keep(alias_ids)
    preferred = _keep([m for m in DEPT_MODEL_CANDIDATES])

    chain = env_ids + [m for m in alias_kept if m not in env_ids]
    chain += [m for m in preferred if m not in chain]

    source = "env" if env_ids else "catalogue_alias"

    # Compatibility tail: the registry's direct-provider ids, still validated.
    try:
        from app.services.model_registry import get_models_for_tier

        registry_models = []
        for tier in ("fast", "mid", "ceo"):
            registry_models.extend(get_models_for_tier(tier, verified_only=True))
        direct = _keep(
            [
                m["canonical_id"]
                for m in registry_models
                if m.get("provider") != "copilot" and not m.get("is_deprecated")
            ]
        )
        for model_id in direct:
            if model_id not in chain:
                chain.append(model_id)
        if not env_ids and not alias_kept and direct:
            source = "registry"
    except Exception as exc:  # noqa: BLE001
        log.warning("Department model resolution: model registry unavailable: %s", exc)

    if dropped:
        log.warning(
            "Department model resolution dropped %d id(s) not in the live "
            "gateway catalogue: %s",
            len(dropped),
            ", ".join(dropped),
        )

    if chain:
        return chain, source

    # Fail soft, and say so. A bare Copilot list is the last resort; it is
    # explicit that the catalogue could not be validated.
    log.error(
        "Department model resolution: no catalogue-validated model; "
        "falling back to DEPT_MODEL_CANDIDATES (%s)",
        ", ".join(DEPT_MODEL_CANDIDATES),
    )
    return list(DEPT_MODEL_CANDIDATES), "fallback_unvalidated"


def _reset_department_model_cache() -> None:
    """Invalidate the resolved chain (tests; operator model swap)."""
    with _DEPT_MODEL_LOCK:
        _DEPT_MODEL_CACHE.update(
            {"resolved_at": 0.0, "chain": (), "source": "unresolved", "error": ""}
        )


def _select_department_model() -> str:
    """Choose the model a department agent's steps run on."""
    return _available_department_models()[0]


def _available_department_models() -> list[str]:
    """Return the department model chain, resolved at runtime and cached.

    Single-flight: one resolution at a time, and the concurrent callers read the
    same chain. Never raises and never returns an empty list -- a resolution
    failure is logged and degrades to the alias list rather than taking the
    agent's tick down with it.

    Copilot-first is deliberately gone. The chain's ids are gateway ids, and the
    Copilot tier is attempted independently by `_execute_llm_step` (which skips
    any id that is not in `COPILOT_MODELS`), so nothing here can strand a tick.
    """
    now = time.monotonic()
    cached = _DEPT_MODEL_CACHE.get("chain") or ()
    if cached and (now - float(_DEPT_MODEL_CACHE.get("resolved_at") or 0.0)) < DEPT_MODEL_CACHE_TTL_SEC:
        return list(cached)

    with _DEPT_MODEL_LOCK:
        # Re-check under the lock: the single flight happens here.
        now = time.monotonic()
        cached = _DEPT_MODEL_CACHE.get("chain") or ()
        if cached and (now - float(_DEPT_MODEL_CACHE.get("resolved_at") or 0.0)) < DEPT_MODEL_CACHE_TTL_SEC:
            return list(cached)
        try:
            chain, source = _resolve_department_models()
        except Exception as exc:  # noqa: BLE001 - resolution must never raise
            log.warning("Department model resolution failed: %s", exc)
            chain, source = list(DEPT_MODEL_CANDIDATES), "fallback_exception"
        chain = [m for m in chain if m] or list(DEPT_MODEL_CANDIDATES)
        _DEPT_MODEL_CACHE.update(
            {
                "resolved_at": time.monotonic(),
                "chain": tuple(chain),
                "source": source,
                "error": "",
            }
        )
        log.info(
            "Department model chain resolved (source=%s): %s",
            source,
            ", ".join(chain),
        )
        return list(chain)



def _normalize_gateway_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
    """Convert OpenAI-style tool_calls into the worker's {name,args} shape.

    2026-08-30: providers differ in shape. DeepInfra sends only
    ``{"id","type","function":{"name","arguments"}}``. Fireworks sends the
    same PLUS a top-level ``"name": null`` — the null key must NOT shadow
    the real ``function.name``. Prefer the ``function`` key whenever it
    carries a truthy name; fall back to a truthy top-level ``name``; skip
    calls with no usable name (never propagate None into tools_used).
    """
    normalized: list[dict[str, Any]] = []
    if not isinstance(tool_calls, list):
        return normalized

    for call in tool_calls:
        if not isinstance(call, dict):
            continue

        # Preferred: OpenAI-compatible function shape.
        fn = call.get("function") if isinstance(call.get("function"), dict) else {}
        fn_name = str(fn.get("name") or "")
        if fn_name:
            raw_args = fn.get("arguments") or {}
            if isinstance(raw_args, str):
                try:
                    args = json.loads(raw_args) if raw_args.strip() else {}
                except Exception:
                    args = {}
            elif isinstance(raw_args, dict):
                args = raw_args
            else:
                args = {}
            normalized.append(
                {"name": fn_name, "args": args, "id": call.get("id")}
            )
            continue

        # Fallback: direct {name, args} shape — only when name is truthy.
        direct_name = str(call.get("name") or "")
        if direct_name:
            args = call.get("args", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except Exception:
                    args = {}
            normalized.append({"name": direct_name, "args": args})
            continue

        # No usable name — skip (caller treats missing entries as "not executed").
    return normalized


def _call_department_gateway_chat(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_tokens: int,
    temperature: float,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    agent_id: str = "dept_worker",
    budget_tier: str = "cost_aware",
) -> tuple[str, dict[str, Any], list[dict[str, Any]], str]:
    """Call the OpenAI-compatible gateway using a canonical worker request."""
    from app.config import settings
    from app.services import ai_gateway
    from app.services.llm_request import build_canonical_worker_request

    trace_id = f"agent-{agent_id}-{uuid.uuid4().hex[:12]}"
    canonical = build_canonical_worker_request(
        model=model,
        messages=messages,
        max_tokens=max_tokens,
        temperature=temperature,
        tools=tools,
        tool_choice=tool_choice,
        agent_id=agent_id,
        trace_id=trace_id,
        task_type="work_mode",
        budget_tier=budget_tier,
    )
    body = canonical.to_openai_chat_body(model=model)
    prepared = ai_gateway.prepare_request(
        settings,
        body,
        agent_id=agent_id,
        trace_id=trace_id,
        source="agent_worker",
        canonical_request=canonical,
    )
    response = ai_gateway.forward_nonstream(settings, prepared)
    choices = response.get("choices") or []
    message = choices[0].get("message", {}) if choices and isinstance(choices[0], dict) else {}
    reply = str(message.get("content") or "")
    usage = response.get("usage") if isinstance(response.get("usage"), dict) else {}
    tool_calls = _normalize_gateway_tool_calls(message.get("tool_calls") or [])
    routed_model = str(response.get("model") or prepared.get("canonical_id") or model)
    return reply, usage, tool_calls, routed_model


def _default_department_model() -> str:
    """The configured fast-tier model, resolved at call time. Never a literal.

    WHY: the two defaults below used to name `deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731`, an id
    DeepSeek stopped listing. Measured 2026-10-20: a caller that passed nothing asked for a model the
    provider does not serve, and the price dict below did not contain the model production actually
    runs, so every department cost estimate fell through to the old DeepInfra rate and understated
    by roughly four times. `app/services/model_ids.py` resolves from LLM_MODEL_<TIER>.
    """
    try:
        from app.services.model_ids import model_for_tier

        return model_for_tier("fast")
    except Exception:  # noqa: BLE001 - a cost estimate must never raise
        return ""


def _estimate_cost(
    tokens_in: int,
    tokens_out: int,
    model: str = "",
) -> float:
    """Estimate LLM cost using the selected department model.

    Prefers the shipped price book (hour-aware, cache-aware, with a `read_at` per entry) and falls
    back to the static table below only if the book cannot be loaded. The static table is a last
    resort, not the truth: `deepseek-flash` is the id production serves and it was missing from it.
    """
    model = model or _default_department_model()
    try:
        from datetime import datetime, timezone

        from app.services.price_book import PriceBook

        book = PriceBook.load()
        provider = "deepseek" if "deepseek" in (model or "") else (model or "").split("/")[0]
        return float(
            book.cost_usd(
                provider=provider,
                model=model,
                prompt_tokens=tokens_in,
                completion_tokens=tokens_out,
                at=datetime.now(timezone.utc),
            )
        )
    except Exception:  # noqa: BLE001 - fall through to the static table
        pass

    rates = {
        "deepseek-flash": (0.30, 1.20),
        "deepseek/deepseek-flash": (0.30, 1.20),
        "deepinfra/deepseek-ai/DeepSeek-V4-Flash-0731": (0.08, 0.18),
        "deepinfra/MiniMaxAI/MiniMax-M3": (0.28, 1.10),
        "deepinfra/deepseek-ai/DeepSeek-V4-Pro-0813": (1.30, 2.60),
        "fireworks/accounts/fireworks/models/deepseek-v4-flash-0731": (0.14, 0.28),
        "deepseek/deepseek-v4-flash": (0.14, 0.28),
        "deepseek-v4-flash": (0.14, 0.28),
        "deepseek-v4-pro": (1.32, 3.96),
        "google/gemini-3.5-flash-lite": (0.30, 2.50),
        "gpt-5.4-mini": (0.10, 0.40),
        "gpt-5-mini": (0.10, 0.40),
    }
    input_rate, output_rate = rates.get(model, (0.08, 0.18))
    return (tokens_in * input_rate + tokens_out * output_rate) / 1_000_000


def _log_llm_usage(
    *,
    db_url: str,
    agent_id: str,
    model: str,
    usage: dict[str, Any] | None,
    latency_ms: int,
    success: bool,
    error_message: str | None = None,
) -> None:
    """Record department-worker LLM usage.

    Keeps budget attribution and troubleshooting tied to the originating
    department agent.
    """
    if not db_url or not agent_id:
        return

    try:
        from app.database import log_model_usage
        from app.pricing import estimate_cost

        cost_est = estimate_cost(
            provider="copilot",
            model=model,
            usage=usage or {},
        )
        log_model_usage(
            db_url,
            agent_id=agent_id,
            provider="copilot",
            model=model,
            tier="fast",
            prompt_tokens=cost_est.prompt_tokens,
            completion_tokens=cost_est.completion_tokens,
            total_tokens=cost_est.total_tokens,
            estimated_cost_usd=cost_est.estimated_cost_usd,
            latency_ms=max(0, int(latency_ms or 0)),
            success=success,
            error_message=error_message,
        )
    except Exception as exc:
        log.warning(
            "Failed to log department LLM usage for %s on %s: %s",
            agent_id,
            model,
            exc,
        )


# ── Productive tick ────────────────────────────────────────────────────


def productive_tick(
    db_url: str,
    agent_id: str,
    tick_number: int = 0,
) -> TickOutcome:
    """Execute one productive work cycle for an agent.

    This is the core loop: claim → context → tools → LLM → execute → report.
    Now with department-scoped tools and autonomy gating.

    Directive 010: Pre-flight budget + circuit breaker gating,
    tick telemetry wrapping, and post-tick anomaly detection.
    """
    start_ms = time.monotonic()

    # ── D010: Circuit breaker gate ─────────────────────────────────
    try:
        from app.services.cost_circuit_breaker import is_circuit_broken

        if is_circuit_broken(agent_id):
            outcome = TickOutcome(
                agent_id=agent_id,
                status="budget_exceeded",
                error="Circuit breaker open for this agent",
            )
            _log_tick(db_url, tick_number, agent_id, outcome)
            return outcome
    except Exception:
        pass  # If breaker module unavailable, proceed

    # Phase 0: Release any stale claims
    release_stale_claims(db_url)

    # Phase 0b: Check for resolved approvals to resume
    _resume_approved_steps(db_url, agent_id)

    # Phase 1: Claim work
    step = claim_next_step(db_url, agent_id)
    if not step:
        outcome = TickOutcome(
            agent_id=agent_id,
            status="idle",
        )
        _log_tick(db_url, tick_number, agent_id, outcome)
        return outcome

    # ── D010: Budget pre-flight ────────────────────────────────────
    # HOUSEKEEPING 2026-08-09: budget check moved AFTER claiming so that
    # standing-work-order steps (source='standing_work_order') are exempt
    # from the speculative dept_pool gate. Previously the dept pool was
    # exhausted by ~midday on initiative ticks, then EVERY productive
    # tick returned budget_exceeded before claiming, so all standing work
    # orders hung until the 30-min lifecycle sweep killed them
    # (5,792 failed WO executions vs 901 success = 86% failure rate).
    # Claiming first lets real scheduled work get through; the global
    # daily limit and pressure gates still protect spend.
    try:
        from app.services.llm_budget import (
            BudgetExceededError,
            check_budget,
        )

        _step_source = str(step.get("source") or "")
        _goal_source = str(step.get("goal_source") or "")
        # Assigned work is exempt from the speculative dept_pool soft gate:
        # standing work orders AND owner/CEO-assigned mission steps are real
        # scheduled work, not initiative/reflection spend. Without this, a
        # dept pool exhausted by midday on speculation blocks every mission
        # step (the strategic-audit goals) until the next UTC day. The
        # global daily limit and rolling-24h gates above still cap absolute
        # spend, so this cannot blow the budget.
        _assigned_step = (
            _goal_source in ("standing_work_order", "mission")
            or _step_source in ("standing_work_order", "mission")
        )
        check_budget(
            db_url,
            agent_id,
            source=(
                "standing_work_order"
                if _assigned_step
                else "productive_tick"
            ),
        )
    except BudgetExceededError as bexc:
        # Budget-blocked before executing: release the claim so the
        # step stays claimable later instead of rotting as 'running'.
        try:
            _release_step_claim(db_url, step["id"], f"budget:{bexc.reason}")
        except Exception:
            pass
        outcome = TickOutcome(
            agent_id=agent_id,
            status="budget_exceeded",
            error=bexc.reason,
            details={
                "spend": bexc.spend,
                "limit": bexc.limit,
            },
        )
        _log_tick(db_url, tick_number, agent_id, outcome)
        return outcome
    except Exception:
        pass  # If budget module unavailable, proceed

    # Phase 1b: Pre-flight skip check — avoid wasting LLM calls
    skip_reason = _should_skip_step(step, agent_id, db_url)
    if skip_reason:
        _release_step_claim(db_url, step["id"], skip_reason)
        log.info(
            "Agent %s skipped step %s (pre-flight): %s",
            agent_id,
            step["id"],
            skip_reason,
        )
        # Check if the skipped/blocked step should be escalated due to missing required tool
        retry_state = {
            "status": "blocked",
            "message": skip_reason,
            "attempts": step.get("attempts", 0),
        }
        result = StepResult(
            action="error",
            result_summary=skip_reason,
        )
        escalation_action = _maybe_escalate_blocked_required_tool_step(
            db_url,
            agent_id,
            step,
            result,
            retry_state,
        )
        outcome = TickOutcome(
            agent_id=agent_id,
            status="skipped_preflight",
            step_id=step["id"],
            goal_id=step["goal_id"],
            error=skip_reason,
            details={
                "step_title": step.get("title"),
                "skip_reason": skip_reason,
                "step_status": "blocked",
                "escalation_action": escalation_action,
            },
        )
        _log_tick(db_url, tick_number, agent_id, outcome)
        return outcome

    # Phase 2: Get working memory for context
    from app.database import _get_conn

    # ── D010: Wrap phases 2-9 in tick telemetry ────────────────────
    try:
        from app.services.tick_telemetry import observe_tick
    except ImportError:
        from contextlib import contextmanager as _cm

        @_cm
        def observe_tick(db_url, agent_id, tick_number=0):  # type: ignore[misc]
            """No-op fallback if tick_telemetry unavailable."""
            yield None

    with observe_tick(db_url, agent_id, tick_number) as tctx:
        conn = _get_conn(db_url)
        wm_row = conn.execute(
            "SELECT context_summary FROM agent_working_memory " "WHERE agent_id = ?",
            (agent_id,),
        ).fetchone()
        working_memory = wm_row["context_summary"] if wm_row else None

        # Get previous step output
        prev = conn.execute(
            "SELECT result_summary FROM goal_steps "
            "WHERE goal_id = ? AND step_number = ? "
            "AND status = 'completed'",
            (step["goal_id"], step["step_number"] - 1),
        ).fetchone()
        prev_output = prev["result_summary"] if prev else None

        # Phase 3: Get department tools
        from app.services.department_tools import (
            get_department_action_names,
            get_department_tools,
            tool_runtime_unavailable_reason,
        )

        tools = get_department_tools(agent_id)
        tool_names = get_department_action_names(agent_id)

        # 2026-10-02: an allow-listed tool this host cannot run must not be
        # presented as callable. `browser_use_run` sits in five allow-lists
        # while its `browser-use` package is absent, so the model called it,
        # every call failed on the import, and the step was released as
        # meta-only with a diagnosis pointing at an allow-list that was already
        # correct. Withhold the schema and say why, once per step.
        unavailable = {
            str((t.get("name") or "")): tool_runtime_unavailable_reason(
                str(t.get("name") or "")
            )
            for t in (tools or [])
        }
        unavailable = {k: v for k, v in unavailable.items() if v}
        if unavailable:
            log.warning(
                "Agent %s step %s: withholding %d tool(s) this host cannot run: %s",
                agent_id,
                step.get("id"),
                len(unavailable),
                "; ".join(f"{k} ({v})" for k, v in sorted(unavailable.items())),
            )
            tools = [
                t
                for t in (tools or [])
                if str(t.get("name") or "") not in unavailable
            ]
        if tool_names is not None:
            tool_names = [
                t for t in tool_names if str(t) not in unavailable
            ]

        # Phase 4: Build focused prompt with department context
        messages = build_focused_prompt(
            step, agent_id, working_memory, prev_output, tool_names
        )

        # Phase 5: Multi-turn LLM call with tools
        try:
            result = _execute_llm_step(
                messages=messages,
                tools=tools if tools else None,
                agent_id=agent_id,
                step_id=step["id"],
                goal_id=step["goal_id"],
                db_url=db_url,
            )
        except Exception as exc:
            log.error(
                "Agent %s LLM call failed for step %s: %s",
                agent_id,
                step["id"],
                exc,
            )
            result = StepResult(
                action="error",
                result_summary=f"LLM call failed: {exc}",
            )

        elapsed_ms = int((time.monotonic() - start_ms) * 1000)
        result.duration_ms = elapsed_ms
        retry_state: dict[str, Any] | None = None
        escalation_action: str | None = None

        if result.action == "complete":
            attempted_tools = result.tools_used
            tools_used = result.tools_executed
            step_desc = step.get("description", "")
            if attempted_tools and not tools_used:
                refusal = ""
                for _detail in result.tool_call_details or []:
                    if _detail.get("error") and _detail.get("result"):
                        refusal = str(_detail.get("result"))[:300]
                        break
                retry_state = _mark_unproductive_step(
                    db_url,
                    step["id"],
                    attempted_tools,
                    reason="no_tool_executed",
                    detail=refusal,
                )
                result.action = "error"
                result.result_summary = (
                    "No tool call executed successfully. "
                    "Invalid or blocked attempts: "
                    f"{', '.join(str(t) for t in attempted_tools)}"
                )
                log.warning(
                    ("Agent %s attempted tools on step %s but " "executed none: %s"),
                    agent_id,
                    step["id"],
                    ", ".join(str(t) for t in attempted_tools),
                )
            elif tools_used and not _has_productive_tool_use(
                tools_used,
                step_desc,
                result.result_summary or "",
            ):
                retry_state = _mark_unproductive_step(
                    db_url,
                    step["id"],
                    tools_used,
                    reason="meta_only",
                )
                result.action = "error"
                result.result_summary = retry_state["message"]
                log.warning(
                    "Agent %s produced meta-only work on step %s: %s",
                    agent_id,
                    step["id"],
                    ", ".join(str(t) for t in tools_used),
                )

        if retry_state is not None:
            escalation_action = _maybe_escalate_blocked_required_tool_step(
                db_url,
                agent_id,
                step,
                result,
                retry_state,
            )

        # ── D010: Populate telemetry context ───────────────────────
        if tctx is not None:
            tctx.set_step(step.get("id"), step.get("goal_id"))
            tctx.llm_rounds = result.tool_rounds
            steps_done = 1 if result.action in ("complete", "skip") else 0
            tctx.set_outcome(
                outcome=result.action,
                cost=result.cost_usd,
                tokens=result.tokens_in + result.tokens_out,
                steps=steps_done,
                error=(result.result_summary if result.action == "error" else None),
            )
# Record tool calls with executed flag and rich outcome for accurate
        # telemetry (args, result preview, latency n/a, approval id).
        for detail in result.tool_call_details:
            _args = detail.get("args") or {}
            _res = str(detail.get("result") or "") or ""
            _appr = detail.get("approval_id")
            tctx.record_tool_call(
                detail["name"],
                _args if isinstance(_args, dict) else {},
                _res,
                int(detail.get("latency_ms") or 0),
                executed=bool(detail.get("executed", True)),
                approval_id=_appr,
                )

        # Phase 6: Update step status
        if retry_state is None:
            complete_step(db_url, step["id"], result)

        # Phase 7: Update working memory if there's context
        if retry_state is None and result.next_step_context:
            from app.database import _db_lock

            with _db_lock:
                conn.execute(
                    "INSERT OR REPLACE INTO agent_working_memory "
                    "(agent_id, context_summary, updated_at) "
                    "VALUES (?, ?, ?)",
                    (
                        agent_id,
                        result.next_step_context,
                        _utc_now().isoformat(),
                    ),
                )
                _commit(conn)

        # Phase 8: Maybe advance goal
        goal_status = None
        if retry_state is None:
            goal_status = maybe_advance_goal(db_url, step["goal_id"])

        # Phase 9: Record step outcome (feedback fan-out)
        record_step_outcome(
            db_url=db_url,
            step_id=step["id"],
            goal_id=step["goal_id"],
            agent_id=agent_id,
            result=result,
            success=(retry_state is None and result.action in ("complete", "skip")),
        )

        # ── D010: Post-tick circuit breaker checks ─────────────────
        # Pass `tool_call_details` (name + args + executed), not bare names: a
        # repeated NAME cannot tell a loop from research, and counting names is
        # what tripped 14 working agents between 2026-09-20 and 09-23.
        # The details list only holds calls the worker actually ran.
        # `db_url` is passed on every check so a trip is persisted — without it
        # `_log_event` and `_persist_state` both no-op and the trip leaves no
        # trace outside the journal (measured: `circuit_breaker_events` held no
        # runaway_loop row for any of the 14 trips).
        try:
            from app.services.cost_circuit_breaker import (
                check_duplicate_tools,
                check_tick_cost,
                check_velocity,
            )

            check_tick_cost(agent_id, result.cost_usd, db_url)
            check_velocity(agent_id, db_url)
            check_duplicate_tools(
                agent_id,
                result.tool_call_details or result.tools_executed,
                db_url,
            )
        except Exception:
            pass

        # ── D010: Post-tick anomaly detection ──────────────────────
        try:
            from app.services.anomaly_detector import (
                check_tick as check_anomalies,
            )

            steps_done = 1 if result.action in ("complete", "skip") else 0
            check_anomalies(
                db_url,
                agent_id,
                tick_cost=result.cost_usd,
                steps_completed=steps_done,
                tool_calls=result.tools_executed,
                tool_call_details=result.tool_call_details,
            )
        except Exception:
            pass

        # ── D013: Post-tick quality grading ────────────────────────
        tick_grade = "unknown"
        try:
            from app.services.tick_quality import grade_tick

            tc_json = json.dumps([{"name": t} for t in result.tools_executed])
            steps_done = 1 if result.action in ("complete", "skip") else 0
            # P5: a tick whose step/session failed is not a productive tick. The
            # closest durable signal available here is the same one the failed-step
            # block below uses (`retry_state` or an error action).
            _session_status = (
                "failed"
                if (retry_state is not None or result.action == "error")
                else None
            )
            tick_grade = grade_tick(
                tc_json,
                result.action,
                steps_done,
                result.cost_usd,
                session_status=_session_status,
            )
            # Persist grade to tick_telemetry
            if tctx is not None:
                tctx.tick_quality = tick_grade
        except Exception:  # noqa: BLE001
            pass

        # ── A failed step is a failed tick ─────────────────────────
        # Measured 2026-09-28: `retry_state` is set only by the tool-quality paths and
        # never by an LLM error, so a step that failed on the model was written as a
        # FAILED step row and a COMPLETED tick -- including the deadlock exit, whose
        # point is that it makes zero provider calls. That discrepancy is why a tick
        # count and a step count disagree, and it flatters the company's own health
        # report. `StepResult.action == "error"` is the signal that was already there.
        _step_action = getattr(result, "action", "") if result is not None else ""
        _step_failed = _step_action == "error"

        outcome = TickOutcome(
            agent_id=agent_id,
            status="error" if (retry_state is not None or _step_failed) else "completed",
            step_id=step["id"],
            goal_id=step["goal_id"],
            result=result,
            details={
                "step_title": step.get("title"),
                "goal_advanced": retry_state is None and goal_status is not None,
                "goal_status": goal_status,
                "step_status": retry_state["status"] if retry_state else None,
                "escalation_action": escalation_action,
                "tools_used": result.tools_used,
                "tools_executed": result.tools_executed,
                "tool_rounds": result.tool_rounds,
            },
        )

        # ── Record probe success for HALF_OPEN circuit breakers ────
        # If this agent completed a tick without tripping, count it
        # as a successful probe toward CLOSED restoration.
        if retry_state is None:
            try:
                from app.services.cost_circuit_breaker import (
                    record_probe_success,
                )

                record_probe_success(agent_id, db_url)
            except Exception:
                pass

        # ── D019: Record outcome signal + procedural experience ────
        try:
            from app.services.evolution_verifier import (
                record_outcome_signal,
            )

            tick_outcome = "success" if retry_state is None else "failure"
            record_outcome_signal(
                agent_id=agent_id,
                action_name="productive_tick",
                outcome=tick_outcome,
                goal_id=step.get("goal_id"),
                score_delta=1.0 if tick_outcome == "success" else -1.0,
                details={
                    "tools_executed": result.tools_executed,
                    "tool_rounds": result.tool_rounds,
                },
            )
        except Exception:
            pass

        try:
            from app.services.procedural_memory import (
                capture_env_state,
                capture_internal_state,
                store_experience,
            )

            env_st = capture_env_state()
            int_st = capture_internal_state(
                agent_id,
                goal_id=step.get("goal_id"),
                step_id=step.get("id"),
            )
            tick_outcome = "success" if retry_state is None else "failure"
            store_experience(
                agent_id=agent_id,
                env_state=env_st,
                internal_state=int_st,
                action_taken="productive_tick",
                action_params={"tools": result.tools_executed[:5]},
                outcome=tick_outcome,
                reward=1.0 if tick_outcome == "success" else -1.0,
            )
        except Exception:
            pass

        _record_cognitive_artifacts(agent_id, step, result, tick_outcome)

        _log_tick(db_url, tick_number, agent_id, outcome)
        return outcome


# ── Approval resume ───────────────────────────────────────────────────


def _resume_approved_steps(db_url: str, agent_id: str) -> int:
    """Find approved actions and execute them, resuming approval-waiting steps.

    Returns count of resumed actions.
    """
    try:
        from app.database import _db_lock, _get_conn

        conn = _get_conn(db_url)
        rows = conn.execute(
            "SELECT * FROM action_approval_queue "
            "WHERE agent_id = ? AND status IN ('approved', 'pending') "
            "ORDER BY CASE WHEN status = 'approved' THEN 0 ELSE 1 END, "
            "         created_at ASC LIMIT 10",
            (agent_id,),
        ).fetchall()

        if not rows:
            return 0

        resumed = 0
        for row in rows:
            row = dict(row)
            tool_name = row["tool_name"]
            step_id = row.get("step_id")
            row_status = row.get("status")
            try:
                args = json.loads(row["arguments"])
            except Exception:
                args = {}

            step_status = None
            if step_id:
                step_row = conn.execute(
                    "SELECT status FROM goal_steps WHERE id = ?",
                    (step_id,),
                ).fetchone()
                if step_row:
                    step_status = step_row["status"]

            if step_id and step_status not in (
                "waiting_approval",
                "suspended",
            ):
                with _db_lock:
                    conn.execute(
                        "UPDATE action_approval_queue "
                        "SET status = 'expired', resolved_at = ? "
                        "WHERE id = ? AND status IN ('approved', 'pending')",
                        (_utc_now().isoformat(), row["id"]),
                    )
                    _commit(conn)
                continue

            # Old pending approvals can become safe after autonomy
            # policy changes.
            if row_status == "pending":
                gate = _check_autonomy(tool_name, agent_id)
                if not gate.get("execute", False):
                    # Expire stale pending approvals (>72h) to
                    # prevent permanent step blockage.
                    _STALE_HOURS = 72
                    try:
                        created = _parse_iso_utc(row["created_at"])
                        age_h = (_utc_now() - created).total_seconds() / 3600
                    except Exception:
                        age_h = 0
                    if age_h >= _STALE_HOURS:
                        now_iso = _utc_now().isoformat()
                        with _db_lock:
                            conn.execute(
                                "UPDATE action_approval_queue "
                                "SET status = 'expired', "
                                "    resolved_at = ? "
                                "WHERE id = ?",
                                (now_iso, row["id"]),
                            )
                            if step_id:
                                conn.execute(
                                    "UPDATE goal_steps "
                                    "SET status = 'pending', "
                                    "    claimed_by = NULL "
                                    "WHERE id = ? AND "
                                    "status = 'waiting_approval'",
                                    (step_id,),
                                )
                            _commit(conn)
                        log.info(
                            "Expired stale pending approval "
                            "#%s (%s, %.0fh old) for %s",
                            row["id"],
                            tool_name,
                            age_h,
                            agent_id,
                        )
                    continue

            # Execute the approved action without re-checking autonomy.
            result_text, executed, _ = _execute_tool_with_autonomy(
                tool_name=tool_name,
                tool_args=args,
                agent_id=agent_id,
                step_id=row.get("step_id"),
                goal_id=row.get("goal_id"),
                db_url=db_url,
                bypass_autonomy=True,
            )

            if not executed:
                log.warning(
                    "Agent %s approved action %s could not be executed: %s",
                    agent_id,
                    row["id"],
                    result_text,
                )
                with _db_lock:
                    conn.execute(
                        "UPDATE action_approval_queue "
                        "SET status = 'rejected', "
                        "    resolved_at = ?, "
                        "    resolved_by = 'execution_failed' "
                        "WHERE id = ?",
                        (_utc_now().isoformat(), row["id"]),
                    )
                    if step_id:
                        conn.execute(
                            (
                                "UPDATE goal_steps "
                                "SET status = 'pending', "
                                "    claimed_by = NULL, "
                                "    result_summary = ?, "
                                "    started_at = NULL, "
                                "    completed_at = NULL "
                                "WHERE id = ? AND status IN "
                                "('waiting_approval', 'suspended')"
                            ),
                            (
                                (
                                    "Approved action failed during "
                                    f"execution: {result_text[:200]}"
                                ),
                                step_id,
                            ),
                        )
                    _commit(conn)
                continue

            # Mark approval as executed
            with _db_lock:
                conn.execute(
                    "UPDATE action_approval_queue "
                    "SET status = 'executed', "
                    "    resolved_at = ? "
                    "WHERE id = ?",
                    (_utc_now().isoformat(), row["id"]),
                )
                _commit(conn)

            goal_status = None

            # If the step was waiting for approval, complete it now.
            if step_id:
                with _db_lock:
                    conn.execute(
                        "UPDATE goal_steps "
                        "SET status = 'completed', "
                        "    claimed_by = NULL, "
                        "    result_summary = ?, "
                        "    completed_at = ? "
                        "WHERE id = ? AND status IN ('waiting_approval', 'suspended')",
                        (
                            f"Approved and executed: {result_text[:200]}",
                            _utc_now().isoformat(),
                            step_id,
                        ),
                    )
                    _commit(conn)

                if row.get("goal_id"):
                    goal_status = maybe_advance_goal(db_url, row["goal_id"])

            resumed += 1
            if goal_status is not None:
                log.info(
                    "Agent %s advanced goal %s after approval execution: %s",
                    agent_id,
                    row.get("goal_id"),
                    goal_status,
                )

        if resumed:
            log.info(
                "Agent %s resumed %d approved actions",
                agent_id,
                resumed,
            )
        return resumed

    except Exception as exc:
        log.debug("Approval resume failed (non-fatal): %s", exc)
        return 0


# ── Feedback fan-out ──────────────────────────────────────────────────


def record_step_outcome(
    db_url: str,
    step_id: int,
    goal_id: str,
    agent_id: str,
    result: StepResult,
    success: bool = True,
) -> None:
    """Fan out step outcomes to all feedback subsystems.

    Updates: autonomy tracking, trigger template stats,
    work metrics, and agent working memory.
    """
    # 1. Autonomy tracking (already done per-tool in _execute_tool)
    #    — no additional work needed here

    # 2. Trigger template stats
    try:
        from app.database import _get_conn

        conn = _get_conn(db_url)
        goal = conn.execute(
            "SELECT source, source_ref FROM goal_plans " "WHERE id = ?",
            (goal_id,),
        ).fetchone()
        if goal and goal["source"] == "trigger":
            try:
                from app.services.trigger_goal_pipeline import (
                    record_template_outcome,
                )

                record_template_outcome(
                    db_url=db_url,
                    trigger_type=goal["source_ref"] or "",
                    success=success,
                )
            except Exception:
                pass
    except Exception:
        pass

    # 3. Work metrics (already logged via _log_tick)

    # 4. Agent working memory — save lessons on errors
    if not success and result.result_summary:
        try:
            from app.database import _db_lock, _get_conn

            conn = _get_conn(db_url)
            lesson = f"Step failed ({result.action}): " f"{result.result_summary[:200]}"
            with _db_lock:
                conn.execute(
                    "INSERT OR REPLACE INTO agent_working_memory "
                    "(agent_id, context_summary, updated_at) "
                    "VALUES (?, ?, ?)",
                    (
                        agent_id,
                        lesson,
                        _utc_now().isoformat(),
                    ),
                )
                _commit(conn)
        except Exception:
            pass


def _log_tick(
    db_url: str,
    tick_number: int,
    agent_id: str,
    outcome: TickOutcome,
) -> None:
    """Record tick activity for metrics."""
    try:
        from app.services.work_metrics import log_tick_activity

        result = outcome.result
        log_tick_activity(
            db_url=db_url,
            tick_number=tick_number,
            agent_id=agent_id,
            was_active=(outcome.status == "completed"),
            action_type=outcome.status,
            step_id=outcome.step_id,
            goal_id=outcome.goal_id,
            tokens_in=result.tokens_in if result else 0,
            tokens_out=result.tokens_out if result else 0,
            cost_usd=result.cost_usd if result else 0.0,
            duration_ms=result.duration_ms if result else 0,
        )
    except Exception as exc:
        log.debug("Tick logging failed (non-fatal): %s", exc)


# ── Initiative tick — proactive domain scanning ───────────────────────

# Department-specific domain prompts for initiative generation
_DEPT_INITIATIVE_PROMPTS: dict[str, str] = {
    "dept_business_ops": (
        "You are the Business Operations department. Scan for: uncontacted customers with open cases, "
        "aging work orders (>48h without update), pricing opportunities, inventory gaps, unanswered "
        "inquiries. Generate 3 specific actionable tasks you should work on TODAY that aren't already "
        "tracked. Be concrete — include customer names, specific devices, or order numbers if known."
    ),
    "dept_finance": (
        "You are the Finance department. Scan for: cash position anomalies, stale transaction sources "
        "(>3 days without sync), unmatched deposits, upcoming tax or payment deadlines, QuickBooks "
        "reconciliation gaps, missing receipts. Generate 3 specific tasks to work on TODAY."
    ),
    "dept_engineering": (
        "You are Engineering. Scan for: open PRs needing review, failing CI, dependency security "
        "alerts, technical debt hotspots, performance regressions, broken integrations. Generate "
        "3 specific engineering tasks to work on TODAY with the repo name and issue type."
    ),
    "dept_research": (
        "You are Research. Scan for: market changes in the device repair/LPT domain, new sourcing "
        "opportunities for common parts, competitor pricing changes, technology changes affecting "
        "operations. Generate 3 research tasks to work on TODAY."
    ),
    "dept_home_life": (
        "You are Home & Life Management. Scan for: Home Assistant automation failures, upcoming "
        "personal commitments needing prep, recurring tasks that are overdue, optimization "
        "opportunities in home routines. Generate 3 specific tasks for TODAY."
    ),
    "dept_world_index": (
        "You are World Index & Continuity. Scan for: stale data sources (>24h without index), "
        "missing context that downstream agents need, VS Code chat sessions not yet ingested, "
        "commitment signals that haven't been captured as tasks. Generate 3 specific indexing "
        "or continuity tasks for TODAY."
    ),
    "dept_scheduling": (
        "You are Scheduling & Commitments. Review the next 72 hours: identify missing prep packets, "
        "scheduling conflicts, commitments made in recent communications not yet calendared, "
        "follow-ups that are overdue. Generate 3 specific scheduling tasks for TODAY."
    ),
    "dept_comms_relationships": (
        "You are Communications & Relationships. Scan for: important messages awaiting reply "
        "(>24h), relationship contacts who haven't been touched in >2 weeks, communications "
        "misses that need follow-up, channel health issues. Generate 3 specific comms tasks for TODAY."
    ),
    "dept_evolution_reliability": (
        "You are Evolution & Reliability. Scan for: recurring error patterns, stale workflows "
        "that haven't run in >3 days, departments with low activity (potential stagnation), "
        "improvement opportunities even when nothing is visibly broken. Generate 3 specific "
        "improvement tasks for TODAY."
    ),
    "evolution_architect": (
        "You are the Evolution Architect reporting to Evolution & Reliability. Scan for flat, "
        "overbroad, or brittle parts of the company operating model. Generate 3 concrete architecture "
        "tasks for TODAY: hierarchy changes, department contracts, handoff protocols, monitors, or "
        "prompt/tool upgrades. Each task must include what should change and how to verify it."
    ),
    "reliability_verifier": (
        "You are the Reliability Verifier reporting to Evolution & Reliability. Scan for tasks closed "
        "without evidence, untested changes, recurring failures, budget blind spots, and customer/finance "
        "safety risks. Generate 3 concrete verification or regression-prevention tasks for TODAY."
    ),
    "model_ops_evaluator": (
        "You are Model Ops Evaluator reporting to Evolution & Reliability. Scan for model-routing, "
        "gateway budget, prompt-cache, local-model, eval-harness, and fallback-policy opportunities. "
        "Generate 3 concrete model-ops tasks for TODAY that reduce cost or improve autonomous quality."
    ),
    "dept_security": (
        "You are Security. Scan for: vulnerable runtime versions or pending OS "
        "security updates on any posture-permitted host, leaked credentials still "
        "live in transcripts/repos/logs, certificates expiring soon, and security "
        "queue rows nobody has moved. Generate 3 specific security tasks for TODAY, "
        "each with the host or credential and the evidence; never print a secret "
        "value, and never plan an action on the frozen office box `secratary`."
    ),
    "dept_devices": (
        "You are Device Operations. Scan for: devices in pipeline without status updates, "
        "setup scripts that may be outdated, inventory levels for common parts, pending "
        "device orders without tracking. Generate 3 specific device ops tasks for TODAY."
    ),
    "dept_creativity": (
        "You are the Creativity & Opportunity department. Your job is to generate NEW ideas "
        "and surface opportunities the owner hasn't thought of. Scan across: business metrics, "
        "market signals, operational patterns, communications patterns, calendar patterns, "
        "and financial signals. Generate 3 specific proposals that would create real value — "
        "be concrete about what the opportunity is, what domain it's in, and what the impact could be. "
        "Format each as: PROPOSAL: [title] | DOMAIN: [business/personal/tech/finance] | "
        "DESCRIPTION: [what and why] | IMPACT: [estimated value/time saved/problem solved]"
    ),
    "creativity_scout": (
        "You are Creativity Scout reporting to Creativity & Opportunity. Scan for raw opportunity "
        "signals across tasks, communications, finance gaps, customer operations, market changes, and "
        "personal-life friction. Generate 3 concrete signal-capture tasks or proposal seeds for TODAY."
    ),
    "proposal_evaluator": (
        "You are Proposal Evaluator reporting to Creativity & Opportunity. Scan the proposal backlog, "
        "recent ideas, and accepted/rejected outcomes. Generate 3 concrete tasks for TODAY to score, "
        "triage, reject weak ideas, or route strong proposals with owner/CEO-ready evidence."
    ),
    "cross_domain_synthesizer": (
        "You are Cross-Domain Synthesizer reporting to Creativity & Opportunity. Connect signals across "
        "at least three departments and generate 3 concrete synthesis tasks or proposals that create "
        "leverage across business, finance, scheduling, comms, devices, and engineering."
    ),
}

_GENERIC_INITIATIVE_PROMPT = (
    "You are a {agent_id} AI agent. Based on your domain expertise, scan for 3 specific "
    "actionable tasks you should work on TODAY that aren't already tracked. Be concrete."
)


def _generic_hierarchy_prompt(agent_id: str) -> str:
    try:
        from app.company_blueprint import get_department_by_id

        dept = get_department_by_id(agent_id)
        if dept:
            layer = str(dept.get("hierarchy_layer") or "department")
            cost_tier = str(dept.get("cost_tier") or "fast")
            reports_to = str(dept.get("reports_to") or "orchestrator")
            review_gate = str(dept.get("review_gate") or "")
            decision_scope = str(dept.get("decision_scope") or "")
            mission = str(dept.get("mission") or "")
            return (
                f"You are {dept.get('name') or agent_id}, {dept.get('role') or 'AI worker'}, "
                f"in a real hierarchical AI company. Layer={layer}; cost_tier={cost_tier}; reports_to={reports_to}. "
                f"Mission: {mission} "
                f"Decision scope: {decision_scope or 'Generate useful work within your lane.'} "
                f"Review gate: {review_gate or 'Route uncertain/high-impact work upward.'} "
                "If you are a cheap clerk/indexer/scout, produce high-volume raw signals and expect most to be rejected. "
                "If you are a reviewer/manager, filter aggressively and send only specific, sourced, reversible, or high-leverage work upward. "
                "Generate 3 concrete tasks or proposal packets for TODAY that fit your layer."
            )
    except Exception:
        pass
    return _GENERIC_INITIATIVE_PROMPT.format(agent_id=agent_id)


# ── F9 (2026-09-10): initiative reply normalization ────────────────────
# Cheap models frequently ignore the "numbered list" instruction and answer
# with the raw JSON envelope, e.g.
#   {"reply": "I'll scan the live context ...", "actions": [{"name": "gmail_list"}]}
# `initiative_tick` splits the reply on newlines and treated every remaining
# line as a task title. A JSON blob is ONE very long line, so the whole
# envelope became a single task title, and the delegation→goal bridge then
# promoted it into a garbage goal plan.
#
# Measured on the secretary 2026-09-10: 16,659 failed goal_plans, "active"
# goals literally titled `"", "actions": [{"name": "gmail_list", ...}]`, and
# a large share of the daily LLM budget spent on unactionable work.
# Substrings that only ever appear in a JSON envelope, never in real prose.
_INITIATIVE_JSON_NOISE = (
    'actions":', 'action":', 'params":', 'reply":', 'tool":',
    'name":', 'arguments":', 'function":', 'type":', 'result":',
)


def _unwrap_json_reply_items(reply: str) -> list[str]:
    """Normalize an initiative-tick LLM reply into clean candidate item lines.

    Unwraps the common JSON envelope shapes cheap models emit and drops
    structural envelope lines, so callers only see human-readable items.
    """
    text = (reply or "").strip()
    if not text:
        return []

    # 1) Whole reply is JSON — prefer its human-readable field.
    if text[0] in "{[":
        parsed = None
        try:
            import json as _json

            parsed = _json.loads(text)
        except Exception:
            parsed = None
        if isinstance(parsed, dict):
            for key in ("reply", "text", "message", "content", "summary"):
                val = parsed.get(key)
                if isinstance(val, str) and val.strip():
                    text = val.strip()
                    break
            else:
                # Envelope carries only actions — nothing human-readable to keep.
                return []
        elif isinstance(parsed, list):
            out: list[str] = []
            for entry in parsed:
                if isinstance(entry, str) and entry.strip():
                    out.append(entry.strip())
                elif isinstance(entry, dict):
                    for key in ("title", "task", "description", "reply", "text"):
                        val = entry.get(key)
                        if isinstance(val, str) and val.strip():
                            out.append(val.strip())
                            break
            return out

    # 2) Line-by-line — strip JSON punctuation + numbering before judging content.
    import re as _re

    cleaned: list[str] = []
    for raw in text.split("\n"):
        line = raw.strip()
        if not line:
            continue
        # Peel only quote/comma/brace wrappers. Brackets are deliberately NOT
        # stripped — `[ACTION]:` and `[PROPOSAL:` are legitimate markers.
        line = line.lstrip("\"'{,} \t")
        # Strip a numbered-list prefix ("1. " / "1) ").
        line = _re.sub(r"^[0-9]+[.)]\s*", "", line).strip()
        if not line or len(line) < 10:
            continue
        low = line.lower()
        # `in` (not startswith): a truncated envelope can be glued to a
        # preamble on one line, e.g. `I'll scan ...", "actions": [...]`.
        if any(token in low for token in _INITIATIVE_JSON_NOISE):
            continue
        if line[0] in "{}[]" and not (
            low.startswith("[action") or low.startswith("[proposal")
        ):
            continue
        cleaned.append(line)
    return cleaned


def initiative_tick(
    db_url: str,
    agent_id: str,
    *,
    tier: str = "fast",
    dry_run: bool = False,
) -> dict[str, Any]:
    """
    Proactive initiative generation — each department scans its domain and
    creates new tasks without being asked.

    This is the core Phase B mechanism that shifts agents from reactive
    queue-processors to autonomous initiative-generators.

    Returns dict with: tasks_created, proposals_created, items (list of generated items)
    """
    tasks_created = 0
    proposals_created = 0
    items: list[dict[str, Any]] = []

    # ── Per-agent task cap: prevent indexer flooding ──
    # Each agent can have at most MAX_INITIATIVE_OPEN_TASKS open tasks
    # created by initiative ticks. Beyond that, skip initiative generation.
    MAX_INITIATIVE_OPEN_TASKS = 5
    try:
        import sqlite3 as _sq3
        conn = _sq3.connect(db_url.replace("sqlite:///", ""))
        existing = conn.execute(
            "SELECT count(*) FROM tasks WHERE assigned_to=? AND status='open' "
            "AND json_extract(metadata_json, '$.source')='initiative_tick'",
            (agent_id,)
        ).fetchone()
        if existing and existing[0] >= MAX_INITIATIVE_OPEN_TASKS:
            log.debug(
                "initiative_tick %s: skipped — %d open initiative tasks (cap=%d)",
                agent_id, existing[0], MAX_INITIATIVE_OPEN_TASKS
            )
            conn.close()
            return {"ok": True, "agent_id": agent_id, "tasks_created": 0, "proposals_created": 0, "items": [], "skipped": True}
        conn.close()
    except Exception:
        pass  # If we can't check, proceed normally

    # Get domain-specific prompt
    domain_prompt = _DEPT_INITIATIVE_PROMPTS.get(agent_id)
    if not domain_prompt:
        domain_prompt = _generic_hierarchy_prompt(agent_id)

    # Build context: recent tasks, memories, and activity for this department
    context_parts: list[str] = []
    try:
        import sqlite3 as _sq3

        conn = _sq3.connect(db_url.replace("sqlite:///", ""))
        conn.row_factory = _sq3.Row

        # Recent open tasks for this department
        open_tasks = conn.execute(
            """
            SELECT title, status, created_at FROM tasks
            WHERE assigned_to = ? AND status NOT IN ('done', 'completed', 'closed')
            ORDER BY created_at DESC LIMIT 10
            """,
            (agent_id,),
        ).fetchall()
        if open_tasks:
            task_lines = [f"- {r['title']} [{r['status']}]" for r in open_tasks]
            context_parts.append("OPEN TASKS:\n" + "\n".join(task_lines))

        # Recent memories for this department
        recent_mems = conn.execute(
            """
            SELECT content FROM memories
            WHERE agent_id = ?
            ORDER BY created_at DESC LIMIT 5
            """,
            (agent_id,),
        ).fetchall()
        if recent_mems:
            mem_lines = [r["content"][:200] for r in recent_mems]
            context_parts.append("RECENT MEMORIES:\n" + "\n".join(mem_lines))

        conn.close()
    except Exception as ctx_exc:
        log.debug("initiative_tick context build failed for %s: %s", agent_id, ctx_exc)

    system_msg = domain_prompt
    if context_parts:
        system_msg += "\n\nCURRENT CONTEXT:\n" + "\n\n".join(context_parts)
    system_msg += (
        "\n\nOUTPUT FORMAT: Return exactly 3 items as a numbered list. "
        "For each: state what to do, why it matters, and what specific action to take. "
        "Be terse. Each item on one line: 'N. [ACTION]: [brief description] | WHY: [reason]'"
    )

    try:
        from app.assistant_chat import run_assistant_chat
        from app.config import settings as _settings

        resp = run_assistant_chat(
            settings=_settings,
            agent_id=agent_id,
            message=system_msg,
            history=[],
            tier=tier,
            call_type="initiative_tick",
        )
        reply = str(resp.get("reply") or "").strip()
    except Exception as llm_exc:
        log.warning("initiative_tick LLM call failed for %s: %s", agent_id, llm_exc)
        return {
            "ok": False,
            "error": str(llm_exc),
            "tasks_created": 0,
            "proposals_created": 0,
            "items": [],
        }

    if not reply:
        return {"ok": True, "tasks_created": 0, "proposals_created": 0, "items": []}

    # Parse the LLM reply and create tasks or proposals
    if not dry_run:
        # F9 (2026-09-10): unwrap JSON envelopes BEFORE splitting into items.
        lines = _unwrap_json_reply_items(reply)
        for line in lines:
            # Strip leading number like "1. " or "1) "
            import re as _re
            clean = _re.sub(r"^[0-9]+[.)]\s*", "", line).strip()
            if not clean or len(clean) < 10:
                continue

            # Creativity department items become proposals
            if agent_id == "dept_creativity" and "PROPOSAL:" in clean.upper():
                try:
                    from app.services.mashgiach import create_proposal

                    # Parse structured proposal format
                    title = clean
                    domain = "general"
                    description = clean
                    impact = ""

                    if "PROPOSAL:" in clean:
                        title = clean.split("PROPOSAL:", 1)[1].split("|")[0].strip()
                    if "DOMAIN:" in clean:
                        domain = clean.split("DOMAIN:", 1)[1].split("|")[0].strip()
                    if "DESCRIPTION:" in clean:
                        description = clean.split("DESCRIPTION:", 1)[1].split("|")[0].strip()
                    if "IMPACT:" in clean:
                        impact = clean.split("IMPACT:", 1)[1].strip()

                    if title and len(title) > 3:
                        create_proposal(
                            db_url,
                            title=title[:200],
                            domain=domain[:50],
                            description=description[:1000],
                            priority=6,
                            impact_estimate=impact[:500],
                        )
                        proposals_created += 1
                        items.append({"type": "proposal", "title": title})
                except Exception as prop_exc:
                    log.debug("Failed to create proposal from initiative: %s", prop_exc)

            else:
                # All other departments: create a task
                try:
                    from app.database import create_task as _create_task

                    # ── Quality filter: reject self-referential junk ──
                    # Indexer agents on cheap models often generate tasks that are
                    # the agent talking to itself ("Should I...", "I notice...")
                    # rather than actionable work items. Drop these.
                    _junk_prefixes = (
                        "Should I", "I should", "I can ", "I need to",
                        "But I", "I notice", "I'm seeing", "Let me",
                        "I've been", "Looking at", "What I'm",
                        "I want to", "I think", "I feel", "I believe",
                        "**Route", "**Tag", "**Close", "**Change", "**Audit",
                        "**Filter", "**3.", "** scheduler", "**1.", "**2.",
                        "I'm analyzing", "I'm a", "As a", "My role",
                        "Here's my", "Here is my", "Let's analyze",
                        "I will", "I'll ", "I could", "I would",
                        "My analysis", "My task", "My job",
                    )
                    _clean = clean.strip() if clean else ""
                    if _clean and any(_clean.startswith(p) for p in _junk_prefixes):
                        log.debug(
                            "initiative_tick %s: dropped self-referential junk: %s",
                            agent_id, _clean[:80]
                        )
                        continue
                    # Also drop lines that are just meta-instructions or signal headers
                    if _clean and (
                        _clean.startswith("**") and "SIGNAL" in _clean
                    ):
                        log.debug(
                            "initiative_tick %s: dropped signal header: %s",
                            agent_id, _clean[:80]
                        )
                        continue

                    # Extract action part for title
                    if "[ACTION]:" in clean:
                        task_title = clean.split("[ACTION]:", 1)[1].split("|")[0].strip()
                    elif ":" in clean and len(clean.split(":", 1)[0]) < 40:
                        task_title = clean.split(":", 1)[1].split("|")[0].strip()
                    else:
                        task_title = clean[:120]

                    # FU13: `clean` is a line of the model's RAW REPLY, and the F9 guard
                    # below only rejects JSON shapes -- a prose line with no colon reaches
                    # the `else` above verbatim and becomes a task title. That is exactly
                    # how `#27060` and `#27061` reached the task table, reproduced by
                    # FU13 from `initiative_tick` and sampled off the authority. Validate
                    # the output of all three branches; an empty title means the
                    # `len(task_title) > 5` check below skips the row entirely.
                    from app.assistant_chat import sanitize_task_title

                    task_title = sanitize_task_title(task_title)

                    # F9 guard: never let a raw JSON envelope become a task title.
                    if task_title and any(
                        marker in task_title
                        for marker in ('"actions"', '{"name"', '"params"', '"reply"')
                    ):
                        log.debug(
                            "initiative_tick %s: dropped JSON-blob title: %s",
                            agent_id, task_title[:80],
                        )
                        continue

                    if task_title and len(task_title) > 5:
                        # Global dedup check: scan across ALL agents for similar
                        # open tasks before creating. This catches cross-agent
                        # duplicates that agent-scoped dedup misses.
                        try:
                            from app.database import find_similar_open_tasks

                            global_dupes = find_similar_open_tasks(
                                db_url, task_title,
                                agent_id=None,  # global scan
                                similarity_threshold=70,
                            )
                            if global_dupes:
                                log.debug(
                                    "initiative_tick %s: global dedup hit for '%s' "
                                    "→ matches #%d (%d%%)",
                                    agent_id, task_title[:60],
                                    global_dupes[0]["id"],
                                    global_dupes[0]["similarity_pct"],
                                )
                                continue
                        except Exception:
                            pass

                        # Use lower dedup threshold (60%) for initiative tasks
                        # to catch more LLM-generated variations of the same idea
                        task_id = _create_task(
                            db_url,
                            title=task_title[:200],
                            description=f"[Initiative tick] {clean[:500]}",
                            agent_id=agent_id,
                            assigned_to=agent_id,
                            priority="medium",
                            dedup_threshold=60,
                            tags=["initiative", "autonomous"],
                            metadata={
                                "source": "initiative_tick",
                                "agent_id": agent_id,
                                "raw_item": clean[:1000],
                            },
                        )
                        if task_id and task_id > 0:
                            tasks_created += 1
                            items.append({"type": "task", "title": task_title, "id": task_id})
                except Exception as task_exc:
                    log.debug("Failed to create task from initiative: %s", task_exc)

    log.info(
        "initiative_tick %s: %d tasks, %d proposals from %d items",
        agent_id,
        tasks_created,
        proposals_created,
        len(items),
    )

    return {
        "ok": True,
        "agent_id": agent_id,
        "tasks_created": tasks_created,
        "proposals_created": proposals_created,
        "items": items,
        "reply_preview": reply[:500],
    }


def run_initiative_cycle(db_url: str, *, tier: str = "fast") -> dict[str, Any]:
    """Run initiative_tick for all departments. Called daily by autopilot."""
    import random

    # Run a subset each time to avoid burning too much budget in one cycle
    PRIORITY_DEPTS = [
        "dept_business_ops",
        "dept_comms_relationships",
        "dept_scheduling",
        "dept_creativity",
        "dept_evolution_reliability",
    ]
    SECONDARY_DEPTS = [
        "dept_finance",
        "dept_engineering",
        "dept_research",
        "dept_home_life",
        "dept_world_index",
        "evolution_architect",
        "reliability_verifier",
        "model_ops_evaluator",
        "creativity_scout",
        "proposal_evaluator",
        "cross_domain_synthesizer",
        "dept_mashgiach",
    ]

    try:
        from app.company_blueprint import get_always_on_bottom_layer_agents

        BOTTOM_LAYER_DEPTS = get_always_on_bottom_layer_agents()
    except Exception:
        BOTTOM_LAYER_DEPTS = []

    # Always run priority; rotate secondary
    depts_to_run = list(PRIORITY_DEPTS)
    # Pick 3 random secondary depts to keep specialist layers moving without a full fan-out.
    depts_to_run.extend(random.sample(SECONDARY_DEPTS, min(3, len(SECONDARY_DEPTS))))
    # Pick a small cheap-worker sample so the floor keeps sensing without a full hierarchy fan-out.
    if BOTTOM_LAYER_DEPTS:
        depts_to_run.extend(random.sample(BOTTOM_LAYER_DEPTS, min(5, len(BOTTOM_LAYER_DEPTS))))
    depts_to_run = list(dict.fromkeys(depts_to_run))

    total_tasks = 0
    total_proposals = 0
    results: list[dict[str, Any]] = []

    for dept_id in depts_to_run:
        try:
            result = initiative_tick(db_url, dept_id, tier=tier)
            total_tasks += result.get("tasks_created", 0)
            total_proposals += result.get("proposals_created", 0)
            results.append(result)
        except Exception as exc:
            log.warning("initiative_cycle dept %s failed: %s", dept_id, exc)
            results.append({"ok": False, "agent_id": dept_id, "error": str(exc)})

    return {
        "ok": True,
        "departments_run": len(results),
        "tasks_created": total_tasks,
        "proposals_created": total_proposals,
        "results": results,
    }

