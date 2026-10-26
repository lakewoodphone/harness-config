"""Shared notification helpers for chat action execution."""

from __future__ import annotations

import hashlib
import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

_SMS_DEDUP_RING: list[tuple[str, str, float]] = []
_SMS_DEDUP_MAX = 20
_SMS_DEDUP_WINDOW_S = 600  # 10 minutes


def _log_action_sms(
    settings: Any,
    to_number: str,
    body: str,
    result: dict[str, Any],
    agent_id: str = "orchestrator",
    from_number: str | None = None,
) -> None:
    """Log an outbound SMS to the sms_log table (best-effort).

    NO-OP when `send_message` already audited the attempt (`_audit_logged`). A second row
    for the same sid double-counts the owner's daily quota and turns a relay SUPPRESS into
    a `failed` - see main.py:6139 and app/sms_service.py:_audited_send.
    """
    if (result or {}).get("_audit_logged"):
        return
    try:
        from app.database import log_sms

        resolved_from_number = str(
            from_number
            or result.get("from_number")
            or getattr(settings, "twilio_phone_number", "")
            or ""
        )
        log_sms(
            db_url=settings.database_url,
            twilio_sid=result.get("sid") if result.get("ok") else None,
            direction="outbound",
            from_number=resolved_from_number,
            to_number=to_number,
            body=body,
            status="sent" if result.get("ok") else "failed",
            error_message=(result.get("error") if not result.get("ok") else None),
            agent_id=agent_id,
        )
    except Exception:
        log.debug("Failed to log outbound SMS to sms_log", exc_info=True)


def _create_approval_task(
    *,
    settings: Any,
    title: str,
    description: str,
    tags: list[str] | None = None,
    dedupe_key: str | None = None,
) -> int | None:
    """Create an approval task for the owner/CEO.

    `dedupe_key` is passed straight to `database.create_task`, whose exact-key
    dedupe is stronger than its default fuzzy title match: one open approval task
    per (action, agent, resource) instead of one per action, and no new row on
    every retry or every tick.

    When a key IS supplied the fuzzy title match is switched off
    (`dedup_threshold=0`), because otherwise it silently wins: measured
    2026-10-26, three refusals of `repo_map` against two different repo paths all
    returned task #30267 — a title-only approval created three days earlier with
    no dedupe key — and the resource-specific key was never written at all. The
    owner would then approve one path believing he had approved the other.
    `dedup_threshold=0` is the estate's existing pattern for exact dedupe
    (`app/services/drn_reliability_api.py`, same comment). Callers that pass no
    key keep the old behaviour.
    """
    try:
        from app import database

        db_url = getattr(settings, "database_url", "")
        if not db_url:
            return None

        task_id = database.create_task(
            db_url,
            title=title,
            description=description,
            priority="high",
            tags=(tags or ["approval"]),
            agent_id=getattr(settings, "primary_agent_id", "orchestrator"),
            assigned_to=getattr(
                settings,
                "primary_agent_id",
                "orchestrator",
            ),
            dedup_threshold=0 if dedupe_key else 80,
            dedupe_key=dedupe_key,
            bypass_ceiling=True,
        )
        # `create_task` returns -1 (not an id) when the active-task ceiling blocks
        # it, and 0 when the insert produced no row. Neither is a task: passing -1
        # on printed "approval task -1" into the agent's tool result and the log,
        # which reads as a queued approval when nothing was recorded anywhere.
        # Measured 2026-10-26: 300 active tasks against a ceiling of 300, so this
        # branch was live.
        try:
            task_id = int(task_id)
        except (TypeError, ValueError):
            return None
        return task_id if task_id > 0 else None
    except Exception:
        return None


def _sms_is_duplicate(to: str, body: str) -> bool:
    """Return True if a substantially similar SMS was sent recently."""
    now = time.monotonic()
    normalized = re.sub(
        r"[0-9:/.]+",
        "",
        body.lower().strip(),
    )
    digest = hashlib.md5(normalized.encode("utf-8", errors="replace")).hexdigest()
    cutoff = now - _SMS_DEDUP_WINDOW_S
    _SMS_DEDUP_RING[:] = [entry for entry in _SMS_DEDUP_RING if entry[2] > cutoff]
    for entry_to, entry_digest, _ in _SMS_DEDUP_RING:
        if entry_to == to and entry_digest == digest:
            return True
    _SMS_DEDUP_RING.append((to, digest, now))
    if len(_SMS_DEDUP_RING) > _SMS_DEDUP_MAX:
        _SMS_DEDUP_RING.pop(0)
    return False


def _sms_has_signature(body: str, signature: str) -> bool:
    """Return True when the last non-empty line matches the signature."""
    for line in reversed(body.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        normalized = stripped.lstrip("-–—").strip().casefold()
        return normalized == signature.casefold()
    return False


def format_agent_sms_body(
    body: str,
    *,
    settings: Any | None = None,
    signature: str | None = None,
) -> str:
    """Append the configured agent SMS signature once, if needed."""
    text = str(body or "").strip()
    if not text:
        return ""

    resolved_signature = str(signature or "").strip()
    if not resolved_signature and settings is not None:
        resolved_signature = str(
            getattr(settings, "agent_sms_signature", "") or ""
        ).strip()
    if not resolved_signature:
        return text
    if _sms_has_signature(text, resolved_signature):
        return text
    return f"{text}\n\n- {resolved_signature}"


__all__ = [
    "_create_approval_task",
    "_log_action_sms",
    "_sms_is_duplicate",
    "format_agent_sms_body",
]
