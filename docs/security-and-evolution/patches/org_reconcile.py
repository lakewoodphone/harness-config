"""Blueprint/tree reconciliation — the half of bootstrap the tick actually needs.

WHY THIS EXISTS
---------------
``workforce.bootstrap_company()`` creates a missing department and re-parents a
misplaced one. But it is **skipped on the authority**: ``/opt/company/.env`` sets
``AUTOPILOT_SKIP_BOOTSTRAP``, and the service says so at startup —

    2026-10-25T18:34:49+0000 INFO app.autopilot: Company bootstrap skipped
    (autopilot_skip_bootstrap=True)

It is skipped for a defensible reason (the box is 4-core / 15 GB and bootstrap
hires and cleans). The defect is that nothing replaced the small part of it the
tick depends on, so on that host **adding a department to ``DEPARTMENTS``
changed nothing at runtime, silently.**

MEASURED CONSEQUENCE — 2026-10-26
---------------------------------
``dept_security`` was added to ``app/company_blueprint.py`` in the working tree
at ``2026-10-25 00:11:32 UTC``; ``company-api`` restarted at ``18:34:46 UTC``
and therefore had it in memory. Its identity record still read::

    hierarchy.role            orchestrator_father      <- the generic seed role
    hierarchy.parent_agent_id null                      <- not under orchestrator
    hierarchy.children        []
    department.department_id  dept_security
    department.department_name "General Operations"     <- orchestrator's own block
    name                      Agent-4193                <- template name
    reflection_count          0
    status                    <absent>

so it was an orphan in the tree. ``company_tick`` dispatches productive ticks
from ``walk_agent_tree(root_id)``, which breadth-first walks
``hierarchy.children``; an orphan is never visited, never calls
``claim_next_step``, and its standing work orders stall until the sweep kills
them:

    goal swo_seed_security_posture_sweep_0c0f6597   failed 2026-10-25T02:26:29Z
    goal swo_seed_security_credential_hygiene_...   failed 2026-10-25T02:26:29Z
    all 9 goal_steps: status=skipped, attempts=0, claimed_by=null

That is the general failure mode for *any* department added to the blueprint on
the authority, so the fix belongs here rather than in a one-off repair.

WHAT IT DOES NOT DO
-------------------
It hires nothing, fires nothing, deletes nothing, and never overwrites an
identity that looks evolved. It only ensures that a department the blueprint
already declares is *reachable from the root* with an active status and its own
department block. Anything it cannot fix (a department with no identity record
at all) is returned as ``missing`` and reported, never silently created — the
caller decides.
"""
from __future__ import annotations

import logging
import re
from typing import Any

log = logging.getLogger(__name__)

# ``_seed_agent`` names a brand-new identity ``Agent-<n>``. A record that still
# carries that name AND has never reflected is a template seed, not a persona,
# so its identity_core may be replaced from the blueprint without destroying
# anything the agent itself chose.
_TEMPLATE_NAME = re.compile(r"^Agent-\d+$")

# Generic department blocks written by the seed. If a department's own block
# still names a *different* department id, it was cloned rather than bootstrapped.
_GENERIC_DEPT_NAMES = {"general operations"}


def _is_template_seed(rec: dict[str, Any]) -> bool:
    name = str(rec.get("name") or "").strip()
    if not _TEMPLATE_NAME.match(name):
        return False
    try:
        if int(rec.get("reflection_count") or 0) != 0:
            return False
    except (TypeError, ValueError):
        return False
    return True


def reconcile_blueprint_tree(root_id: str = "orchestrator") -> dict[str, Any]:
    """Make every blueprint department reachable from ``root_id``.

    Idempotent and cheap: pure dict work over the department list, no LLM, no
    hiring, no deletion. Safe to call on every ``company_tick``.

    Returns a summary of exactly what was changed, so the caller can log a
    non-empty result loudly and let ``mashgiach`` treat a non-empty repair as a
    finding rather than as health.
    """
    # Imported lazily: workforce imports this module, so a module-level import
    # would be circular.
    from app.company_blueprint import DEPARTMENTS
    from app.workforce import (
        _agent_children,
        _agent_department,
        _save_agent_field,
        get_agent_raw,
    )

    repaired: list[dict[str, str]] = []
    missing: list[str] = []
    orphans: list[str] = []

    root = get_agent_raw(root_id)
    if not root:
        return {
            "ok": False,
            "error": f"root agent {root_id!r} not found",
            "repaired": [],
            "missing": [],
        }

    for dept_def in DEPARTMENTS:
        aid = str(dept_def.get("agent_id") or "").strip()
        if not aid:
            continue
        parent_id = str(dept_def.get("reports_to") or root_id).strip() or root_id

        rec = get_agent_raw(aid)
        if not rec:
            missing.append(aid)
            continue

        hierarchy = dict(rec.get("hierarchy") or {})
        actual_parent = str(hierarchy.get("parent_agent_id") or "").strip() or None
        changed: list[str] = []

        # ── 1. Parentage: reachable, or repaired ────────────────────────
        if actual_parent != parent_id:
            try:
                from app.workforce import reassign_agent_parent

                res = reassign_agent_parent(
                    agent_id=aid,
                    new_parent_agent_id=parent_id,
                    actor_agent_id=root_id,
                )
                if res.get("ok") is False:
                    # A refusal is reported, never retried blindly.
                    orphans.append(f"{aid}:reassign_refused:{res.get('error')}")
                    continue
                changed.append(f"parent {actual_parent or 'null'} -> {parent_id}")
                rec = get_agent_raw(aid) or rec
                hierarchy = dict(rec.get("hierarchy") or {})
            except Exception as exc:  # noqa: BLE001 - reported, not swallowed
                orphans.append(f"{aid}:reassign_error:{exc}")
                continue
        else:
            # Parent is right; make sure the parent actually lists the child,
            # because walk_agent_tree reads the children list, not the parent
            # field. A one-sided link is exactly as invisible as no link.
            parent = get_agent_raw(parent_id)
            if parent:
                kids = _agent_children(parent)
                if aid not in kids:
                    kids.append(aid)
                    ph = dict(parent.get("hierarchy") or {})
                    ph["children"] = kids
                    _save_agent_field(parent_id, "hierarchy", ph)
                    changed.append(f"added to {parent_id}.children")

        # ── 2. Status: a department the blueprint declares is active ────
        if str(rec.get("status") or "").strip().lower() != "active":
            _save_agent_field(aid, "status", "active")
            changed.append(f"status {rec.get('status') or 'null'} -> active")

        # ── 3. Department block: its own, not the parent's clone ────────
        dept_data = dict(_agent_department(rec) or {})
        cloned = (
            str(dept_data.get("department_id") or "").strip() not in ("", aid)
            or str(dept_data.get("department_name") or "").strip().lower()
            in _GENERIC_DEPT_NAMES
        )
        if cloned or dept_data.get("status") != "active":
            dept_data.update(
                {
                    "department_id": aid,
                    "department_name": str(dept_def.get("name") or aid),
                    "manager_agent_id": aid,
                    "parent_department_id": parent_id,
                    "status": "active",
                }
            )
            _save_agent_field(aid, "department", dept_data)
            changed.append("department block -> own")

        # ── 4. Identity: only for a record that never became a persona ──
        # Never overwritten for an agent with reflections of its own: organic
        # evolution outranks the blueprint (the same rule bootstrap_company
        # states in its docstring).
        if _is_template_seed(rec):
            core = dict(rec.get("identity_core") or {})
            want_mission = str(dept_def.get("mission") or "").strip()
            want_role = str(dept_def.get("role") or "").strip()
            if want_mission and core.get("mission") != want_mission:
                core["mission"] = want_mission
                _save_agent_field(aid, "identity_core", core)
                changed.append("identity_core.mission -> blueprint")
            if want_role and hierarchy.get("role") != want_role:
                hierarchy = dict(rec.get("hierarchy") or {})
                hierarchy["role"] = want_role
                _save_agent_field(aid, "hierarchy", hierarchy)
                changed.append(f"hierarchy.role -> {want_role!r}")

        if changed:
            repaired.append({"agent_id": aid, "changes": "; ".join(changed)})
            log.warning(
                "org_reconcile: repaired %s (%s)", aid, "; ".join(changed)
            )

    result = {
        "ok": True,
        "repaired": repaired,
        "missing": missing,
        "errors": orphans,
        "repaired_count": len(repaired),
    }
    if repaired or missing or orphans:
        # Quiet is the healthy state; anything else must be visible.
        log.warning(
            "org_reconcile: %d repaired, %d missing identity, %d error(s)",
            len(repaired),
            len(missing),
            len(orphans),
        )
    return result
