#!/usr/bin/env python3
"""Make BOTH budget sites consult the extension, not just the one I happened to patch.

The first version of the budget extension was placed before the pre-tick guard, and
live evidence immediately showed it never fired:

  session 75414 (task #25118), step 5 was `update_task` -- a mutating action -- so
  _work_session_is_progressing should have returned True, and yet:
  [STEP_BUDGET_EXHAUSTED: reached planned 5/5 work steps without [WORK_DONE]]

"reached planned 5/5 work steps" is the wording of the SECOND site, the check inside the
step loop (`if current_step >= total_steps:` at the end of each step). That is the site
that actually fires at 5/5, and it was left untouched. 39 unit tests passed because they
tested the helper, not the interception.

Fix: one helper, called from both sites. The helper is also now testable in isolation
for its condition, and a structural test asserts that every budget-decision site in the
work loop goes through it -- which is precisely the mistake this event was.
"""

from __future__ import annotations

import ast
import os
import pathlib
import shutil
import time

ROOT = pathlib.Path("/home/zabz/personal-secretary-mvp")
os.chdir(ROOT)
STAMP = time.strftime("%Y%m%d-%H%M%S")
BACKUPS = ROOT / ".runtime" / "deploy-backups"
BACKUPS.mkdir(parents=True, exist_ok=True)

HELPER = '''    def _maybe_extend_work_session_budget(
        self,
        *,
        steps_taken: int,
        total_steps: int,
        accumulated_output: str,
        session_id: int,
        update_work_session: Any,
        proactive_actions: list[str],
    ) -> int:
        """Give a progressing session more room; return the (possibly raised) total.

        ONE SOURCE OF TRUTH FOR BOTH BUDGET DECISIONS: the guard that runs before a
        tick and the check inside the step loop. The first version of this extension
        was wired into the guard only, so it never fired -- the in-loop site is the one
        that actually triggers at 5/5. A helper with two callers is the difference.

        Extends only when the session's recent persisted steps took a real action, and
        never past _WORK_ABSOLUTE_MAX_STEPS, so an exploring or looping session is still
        stopped exactly as before.
        """
        if steps_taken < total_steps:
            return total_steps
        if total_steps >= self._WORK_ABSOLUTE_MAX_STEPS:
            return total_steps
        if not self._work_session_is_progressing(accumulated_output):
            return total_steps

        new_total = min(
            total_steps + self._WORK_STEP_EXTENSION,
            self._WORK_ABSOLUTE_MAX_STEPS,
        )
        update_work_session(
            db_url=self._db_url,
            session_id=session_id,
            total_steps=new_total,
            output_append=(
                f"[BUDGET-EXTENDED: {total_steps} -> {new_total} steps. The recent "
                "steps took real actions, so the session continues rather than being "
                "discarded at a limit fixed before the work started.]"
            ),
        )
        proactive_actions.append(
            f"Work session {session_id}: budget extended {total_steps} -> {new_total}"
        )
        return new_total

    @classmethod
    def _consecutive_readonly_steps(cls, accumulated_output: str) -> int:'''

# the guard version I added last round, now replaced by a call to the helper
OLD_GUARD_BLOCK = '''        # ── Budget extension: a checkpoint, not a death sentence ──
        # Placed BEFORE the guard below so the guard sees the extended total and
        # does not discard a session that is still doing work. 143 of 222 failures
        # in the 24h to 2026-09-14 were this budget firing at exactly 5/5.
        if (
            steps_done >= total_steps
            and total_steps < self._WORK_ABSOLUTE_MAX_STEPS
            and self._work_session_is_progressing(accumulated_output)
        ):
            new_total = min(
                total_steps + self._WORK_STEP_EXTENSION,
                self._WORK_ABSOLUTE_MAX_STEPS,
            )
            update_work_session(
                db_url=self._db_url,
                session_id=session_id,
                total_steps=new_total,
                output_append=(
                    f"[BUDGET-EXTENDED: {total_steps} -> {new_total} steps. The "
                    "recent steps took real actions, so the session continues "
                    "rather than being discarded at a limit fixed before the work "
                    "started.]"
                ),
            )
            proactive_actions.append(
                f"Work session {session_id}: budget extended {total_steps} -> {new_total}"
            )
            total_steps = new_total

        # ── Guard: auto-complete if already at or past total steps ──
        if steps_done >= total_steps:'''

NEW_GUARD_BLOCK = '''        # ── Budget extension: a checkpoint, not a death sentence ──
        # 143 of 222 failures in the 24h to 2026-09-14 were this budget firing at
        # exactly 5/5. The same helper is called at the in-loop check, which is the
        # site that actually triggers; wiring only this one is why the first version
        # of this fix never fired.
        total_steps = self._maybe_extend_work_session_budget(
            steps_taken=steps_done,
            total_steps=total_steps,
            accumulated_output=accumulated_output,
            session_id=session_id,
            update_work_session=update_work_session,
            proactive_actions=proactive_actions,
        )

        # ── Guard: auto-complete if already at or past total steps ──
        if steps_done >= total_steps:'''

OLD_IN_LOOP = '''                if current_step >= total_steps:
                    if artifact_required and not self._work_output_has_completion_artifact('''

NEW_IN_LOOP = '''                # The site that actually fires at 5/5. Consult the same helper as the
                # pre-tick guard so a progressing session is extended here too.
                total_steps = self._maybe_extend_work_session_budget(
                    steps_taken=current_step,
                    total_steps=total_steps,
                    accumulated_output=accumulated_output,
                    session_id=session_id,
                    update_work_session=update_work_session,
                    proactive_actions=proactive_actions,
                )
                if current_step >= total_steps:
                    if artifact_required and not self._work_output_has_completion_artifact('''

TEST = '''"""Every budget-decision site in the work loop must consult the extension.

The first version wired the extension into the pre-tick guard only. Live evidence
(secratary, session 75414) showed it never fired even though step 5 was a mutating
action: the failure marker read "reached planned 5/5 work steps", which is the wording
of the IN-LOOP site, the one that actually triggers at 5/5.

This asserts the wiring structurally, because the helper's own logic is covered by
tests/test_budget_extension.py -- what was missing was that both callers use it.
"""

import ast
import pathlib

from app.autopilot import AutopilotController as AC

LOOP = AC._process_work_queue


def _loop_source():
    src = pathlib.Path(AC.__module__.replace(".", "/") + ".py")
    path = pathlib.Path(__file__).resolve().parents[1] / "app" / "autopilot.py"
    return path.read_text(encoding="utf-8")


def test_the_work_loop_calls_the_extension_helper_at_two_sites():
    tree = ast.parse(_loop_source())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_work_queue":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_maybe_extend_work_session_budget"
            ]
            assert len(calls) >= 2, (
                f"_process_work_queue consults the budget extension {len(calls)} time(s); "
                "both the pre-tick guard and the in-loop check must call it"
            )
            return
    raise AssertionError("_process_work_queue not found")


def test_the_helper_extends_only_when_a_real_action_happened():
    """Condition, in isolation: read-only work earns nothing."""
    ap = AC.__new__(AC)
    calls = []
    ap._db_url = "x"
    ap._readonly_free = None

    def fake_update(**kw):
        calls.append(kw)

    read_only = "Step 1: a [ACTIONS: 2 (ha_states, list_tasks)]\\nStep 2: b [ACTIONS: 1 (qb_status)]\\n"
    got = ap._maybe_extend_work_session_budget(
        steps_taken=5, total_steps=5, accumulated_output=read_only,
        session_id=1, update_work_session=fake_update, proactive_actions=[],
    )
    assert got == 5 and calls == []


def test_the_helper_extends_a_progressing_session():
    ap = AC.__new__(AC)
    ap._db_url = "x"
    calls = []
    notes = []
    acting = "Step 1: a [ACTIONS: 1 (ha_states)]\\nStep 2: b [ACTIONS: 1 (update_task)]\\n"
    got = ap._maybe_extend_work_session_budget(
        steps_taken=5, total_steps=5, accumulated_output=acting,
        session_id=7, update_work_session=lambda **kw: calls.append(kw),
        proactive_actions=notes,
    )
    assert got == 8, got
    assert calls and calls[0]["total_steps"] == 8 and calls[0]["session_id"] == 7
    assert notes and "extended 5 -> 8" in notes[0]


def test_the_helper_never_exceeds_the_absolute_cap():
    ap = AC.__new__(AC)
    ap._db_url = "x"
    acting = "Step 1: x [ACTIONS: 1 (update_task)]\\n"
    got = ap._maybe_extend_work_session_budget(
        steps_taken=AC._WORK_ABSOLUTE_MAX_STEPS,
        total_steps=AC._WORK_ABSOLUTE_MAX_STEPS,
        accumulated_output=acting, session_id=1,
        update_work_session=lambda **kw: None, proactive_actions=[],
    )
    assert got == AC._WORK_ABSOLUTE_MAX_STEPS


def test_the_helper_does_nothing_before_the_budget_is_reached():
    ap = AC.__new__(AC)
    ap._db_url = "x"
    acting = "Step 1: x [ACTIONS: 1 (update_task)]\\n"
    got = ap._maybe_extend_work_session_budget(
        steps_taken=2, total_steps=5, accumulated_output=acting, session_id=1,
        update_work_session=lambda **kw: None, proactive_actions=[],
    )
    assert got == 5
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    anchor = "    @classmethod\n    def _consecutive_readonly_steps(cls, accumulated_output: str) -> int:"
    assert src.count(anchor) == 1, f"anchor: {src.count(anchor)}"
    assert src.count(OLD_GUARD_BLOCK) == 1, f"guard block: {src.count(OLD_GUARD_BLOCK)}"
    assert src.count(OLD_IN_LOOP) == 1, f"in-loop: {src.count(OLD_IN_LOOP)}"
    assert "_maybe_extend_work_session_budget" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak7"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(anchor, HELPER)
    src = src.replace(OLD_GUARD_BLOCK, NEW_GUARD_BLOCK)
    src = src.replace(OLD_IN_LOOP, NEW_IN_LOOP)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    # structural proof that both sites now call the helper
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_process_work_queue":
            calls = [
                n for n in ast.walk(node)
                if isinstance(n, ast.Call)
                and isinstance(n.func, ast.Attribute)
                and n.func.attr == "_maybe_extend_work_session_budget"
            ]
            assert len(calls) >= 2, f"only {len(calls)} call site(s)"
            print(f"confirmed: {len(calls)} call sites in _process_work_queue")
            break
    else:
        raise AssertionError("_process_work_queue not found after patching")

    pathlib.Path("tests/test_budget_wiring.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_budget_wiring.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
