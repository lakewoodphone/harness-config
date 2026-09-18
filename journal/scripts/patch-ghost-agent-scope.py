#!/usr/bin/env python3
"""A ghost-agent detector that covers two of three tables reports health it does not have.

MEASURED on secratary 2026-09-15: task #25083 ("Review CHEMED test results and radiology
reports" -- a personal medical item whose own description says "Owner needs to review") had sat
`in_progress` for 5.7 hours assigned to `dept_executive`, which exists NOWHERE: zero occurrences
in company_blueprint.py, and `canonicalize_assignment_agent` returned it unchanged.

Why nothing caught it, exactly:

  * `self_healing_monitor._check_ghost_agents` scans only `goal_plans.assigned_agent` and
    `goal_steps.assigned_agent`. It does not look at `tasks.assigned_to` -- the table the live
    work is in. Its own resolution hint says "reassign to a live department agent or add the
    alias", and it was never in a position to say that about this row.
  * `_normalize_assignment_alias_rows`, which DOES repair `tasks` and runs at schema init, only
    fixes names that are already in `_LEGACY_ASSIGNMENT_AGENT_ALIASES`. `dept_executive` was not
    in the map -- although `executive`, `dept_ceo` and `dept_executive_assistant` all map to
    `orchestrator`, and the map's own comment discusses this very CHEMED plan.

So the name fell between a detector that does not scan the table and a normaliser that only
knows the names someone already thought of. Two fixes:

  1. the missing alias, consistent with its three siblings;
  2. the detector now scans `tasks.assigned_to` for live tasks, so the next unmapped ghost in
     the table where work lives is reported instead of sitting invisible.
"""

from __future__ import annotations

import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

OLD_ALIAS = '''    "dept_executive_assistant": "orchestrator",
}'''
NEW_ALIAS = '''    "dept_executive_assistant": "orchestrator",
    # 2026-09-15: the bare `dept_executive`, which all three of its siblings above already
    # cover. Task #25083 -- the CHEMED/radiology owner-review item those comments discuss --
    # was assigned to it and sat in_progress for 5.7h, invisible to the ghost-agent monitor
    # because that scans goal_plans and goal_steps and not `tasks`. Zero occurrences in
    # company_blueprint.py, so it is a ghost, not a department.
    "dept_executive": "orchestrator",
}'''

OLD_LOOP = '''    fixed = 0
    for tbl, col in (("goal_plans", "assigned_agent"), ("goal_steps", "assigned_agent")):
        try:
            rows = conn.execute(
                f"""SELECT id, {col} FROM {tbl}
                    WHERE status NOT IN ('completed','cancelled','failed','skipped')
                      AND {col} IS NOT NULL AND {col} != ''"""
            ).fetchall()'''

NEW_LOOP = '''    fixed = 0
    # `tasks` is where the LIVE work is, and it was the one table not scanned: task #25083
    # sat in_progress for 5.7h assigned to a name that exists nowhere, while this check
    # reported zero ghosts because it only looked at goal_plans and goal_steps.
    targets = (
        (
            "goal_plans",
            "assigned_agent",
            "status NOT IN ('completed','cancelled','failed','skipped')",
        ),
        (
            "goal_steps",
            "assigned_agent",
            "status NOT IN ('completed','cancelled','failed','skipped')",
        ),
        (
            "tasks",
            "assigned_to",
            "status IN ('open','in_progress','pending','blocked','todo','paused',"
            "'in-progress','waiting on customer','waiting_on_customer','awaiting_part')",
        ),
    )
    for tbl, col, status_clause in targets:
        try:
            rows = conn.execute(
                f"""SELECT id, {col} FROM {tbl}
                    WHERE {status_clause}
                      AND {col} IS NOT NULL AND {col} != ''"""
            ).fetchall()'''

TEST = '''"""The ghost-agent detector must scan the table the live work is in.

Measured on secratary 2026-09-15: task #25083 -- a personal medical item ("CHEMED test results
and radiology reports", "Owner needs to review") -- sat in_progress for 5.7h assigned to
`dept_executive`, which exists nowhere. Nothing caught it: _check_ghost_agents scanned only
goal_plans and goal_steps, and the alias normaliser only fixes names already in the map, where
`executive`, `dept_ceo` and `dept_executive_assistant` were covered and the bare form was not.
"""

import ast
import pathlib

from app.database import _LEGACY_ASSIGNMENT_AGENT_ALIASES, canonicalize_assignment_agent


def test_the_bare_dept_executive_maps_like_its_siblings():
    assert canonicalize_assignment_agent("dept_executive") == "orchestrator"
    for sibling in ("executive", "dept_ceo", "dept_executive_assistant"):
        assert _LEGACY_ASSIGNMENT_AGENT_ALIASES.get(sibling) == "orchestrator"


def test_an_unknown_name_is_still_left_alone():
    """The map is explicit on purpose; a new department must not be silently rerouted."""
    assert canonicalize_assignment_agent("dept_brand_new_thing") == "dept_brand_new_thing"


def test_the_detector_scans_tasks_assigned_to():
    """Wiring, asserted structurally: this is the table that was missing.

    A behavioural test would need the monitor's roster, finding recorder and cooldown state,
    which would end up testing a harness rather than the rule. What went wrong here was the
    SCOPE of the scan, and scope is visible in the source.
    """
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "services" / "self_healing_monitor.py"
    src = path.read_text(encoding="utf-8")
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_check_ghost_agents":
            pairs = {
                (elt.elts[0].value, elt.elts[1].value)
                for elt in ast.walk(node)
                if isinstance(elt, ast.Tuple)
                and len(elt.elts) == 3
                and all(isinstance(e, ast.Constant) for e in elt.elts)
            }
            assert ("tasks", "assigned_to") in pairs, sorted(pairs)
            assert ("goal_plans", "assigned_agent") in pairs
            assert ("goal_steps", "assigned_agent") in pairs
            return
    raise AssertionError("_check_ghost_agents not found")


def test_every_live_task_assignment_is_canonicalisable_or_known():
    """A live check against the real table would go here; kept as a rule statement.

    The detector reports the ones that are neither, once, with a cooldown -- that is the
    mechanism that should have produced a finding for task #25083 and now can.
    """
    assert canonicalize_assignment_agent(None) is None
    assert canonicalize_assignment_agent("") is None
    assert canonicalize_assignment_agent("  orchestrator  ") == "orchestrator"
'''


def main() -> int:
    db = pathlib.Path("app/database.py")
    src = db.read_text(encoding="utf-8")
    mon = pathlib.Path("app/services/self_healing_monitor.py")
    msrc = mon.read_text(encoding="utf-8")

    assert src.count(OLD_ALIAS) == 1, f"alias anchor: {src.count(OLD_ALIAS)}"
    assert '"dept_executive":' not in src, "the alias is already present"
    assert msrc.count(OLD_LOOP) == 1, f"loop anchor: {msrc.count(OLD_LOOP)}"

    for rel in ("app/database.py", "app/services/self_healing_monitor.py"):
        backup = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak16"
        if not backup.exists():
            shutil.copy(rel, backup)

    db.write_text(src.replace(OLD_ALIAS, NEW_ALIAS), encoding="utf-8")
    mon.write_text(msrc.replace(OLD_LOOP, NEW_LOOP), encoding="utf-8")
    print("patched the alias map and the ghost-agent detector")

    pathlib.Path("tests/test_ghost_agent_scope.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_ghost_agent_scope.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
