#!/usr/bin/env python3
"""A work-session budget is a checkpoint, not a death sentence.

MEASURED, secratary 2026-09-14: 143 of 222 failures in 24 hours were
STEP_BUDGET_EXHAUSTED at exactly 5/5, and the budget is not a measure of the work --
it is a number chosen before the work started. Session 75410 (verify a Fios service
address) ran five steps of mutating work with tool results finally reaching it and
was still discarded; 75411 completed the same night in four steps. A session that is
demonstrably working should be given room to finish, and a session that is not should
still be stopped.

HOW "DEMONSTRABLY WORKING" IS DECIDED: from the persisted step markers, checking
whether the last few steps executed a non-read-only action. Not from the in-memory
`_readonly_steps` counter: that is reset at the top of every tick, and since the
queue runs one step per tick it can never even reach the threshold that gates the
STOP SEARCHING nudge. A counter that resets every tick cannot answer a question that
spans ticks, and this one was silently dead in production for that reason.
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

# ── 1. the constants ───────────────────────────────────────────────────────
OLD_CONSTS = """    _WORK_MAX_STEPS = 5
    _WORK_STEP_TIMEOUT = 60  # seconds per LLM step"""

NEW_CONSTS = """    _WORK_MAX_STEPS = 5
    # A session that is making progress earns more room; one that is not is still
    # stopped. The absolute cap is the same 15 the old `total_steps * 3` ceiling
    # produced, so nothing that works today changes -- but it no longer scales with
    # an extended budget, which would have made it unreachable.
    _WORK_STEP_EXTENSION = 3
    _WORK_ABSOLUTE_MAX_STEPS = 15
    _PROGRESS_STEP_WINDOW = 3
    _WORK_STEP_TIMEOUT = 60  # seconds per LLM step"""

# ── 2. the progress test, beside the other action helpers ──────────────────
ANCHOR = "    @classmethod\n    def _actions_are_read_only(cls, actions: list[Any]) -> bool:"

HELPER = '''    @classmethod
    def _work_session_is_progressing(cls, accumulated_output: str) -> bool:
        """True when the session's recent steps took a non-read-only action.

        This is how a budget extension is earned. It reads the PERSISTED step
        markers, not the in-memory `_readonly_steps` counter: that one is reset at
        the top of every tick, and because the queue executes a single step per tick
        it never even reaches the threshold gating the STOP SEARCHING nudge. A
        counter that resets every tick cannot answer a question that spans ticks.
        """
        markers = re.findall(
            r"\\[ACTIONS:\\s*\\d+\\s*\\(([^)]*)\\)\\]", accumulated_output or ""
        )
        if not markers:
            return False
        for names in markers[-cls._PROGRESS_STEP_WINDOW:]:
            for name in (n.strip() for n in names.split(",")):
                if not name:
                    continue
                read_only = name in cls._READ_ONLY_ACTIONS or name.startswith(
                    cls._READ_ONLY_ACTION_PREFIXES
                )
                if not read_only:
                    return True
        return False

    @classmethod
    def _actions_are_read_only(cls, actions: list[Any]) -> bool:'''

# ── 3. extend before the guard that would discard the session ──────────────
OLD_GUARD = """        # ── Guard: auto-complete if already at or past total steps ──
        if steps_done >= total_steps:"""

NEW_GUARD = """        # ── Budget extension: a checkpoint, not a death sentence ──
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
        if steps_done >= total_steps:"""

TEST = '''"""A session that is doing real work must not be discarded by its step budget.

Measured on secratary 2026-09-14: 143 of 222 failures in 24 hours were
STEP_BUDGET_EXHAUSTED at exactly 5/5. Session 75410 did five steps of mutating work
with tool results finally reaching it and was still discarded; session 75411
completed in four steps. The budget is a number fixed before the work started, so it
cannot by itself be a verdict on the work.
"""

from app.autopilot import AutopilotController


def _progressing(text):
    return AutopilotController._work_session_is_progressing(text)


def test_read_only_steps_earn_nothing():
    text = "Step 1: x [ACTIONS: 2 (ha_states, list_tasks)]\\nStep 2: y [ACTIONS: 1 (qb_status)]\\n"
    assert _progressing(text) is False


def test_a_mutating_action_earns_more_room():
    text = "Step 1: x [ACTIONS: 2 (ha_states, list_tasks)]\\nStep 2: y [ACTIONS: 1 (update_task)]\\n"
    assert _progressing(text) is True


def test_only_the_recent_window_counts():
    """A mutating action four steps back is not evidence of current progress."""
    text = (
        "Step 1: closure [ACTIONS: 1 (close_task)]\\n"
        "Step 2: a [ACTIONS: 1 (list_tasks)]\\n"
        "Step 3: b [ACTIONS: 1 (ha_states)]\\n"
        "Step 4: c [ACTIONS: 1 (qb_status)]\\n"
    )
    assert _progressing(text) is False


def test_a_step_with_no_actions_is_not_progress():
    assert _progressing("Step 1: only prose, no tools\\n") is False
    assert _progressing("") is False
    assert _progressing(None) is False


def test_the_marker_with_the_feedback_suffix_still_parses():
    text = "Step 1: x [ACTIONS: 2 (list_tasks, save_memory)] [TOOL-RESULTS-FED: 776c]\\n"
    assert _progressing(text) is True


def test_the_absolute_cap_is_finite():
    """Extension must be bounded: a stuck session cannot run forever."""
    assert AutopilotController._WORK_ABSOLUTE_MAX_STEPS > AutopilotController._WORK_MAX_STEPS
    assert AutopilotController._WORK_ABSOLUTE_MAX_STEPS <= 30
    assert AutopilotController._WORK_STEP_EXTENSION > 0
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    assert src.count(OLD_CONSTS) == 1, f"constants: {src.count(OLD_CONSTS)}"
    assert src.count(ANCHOR) == 1, f"helper anchor: {src.count(ANCHOR)}"
    assert src.count(OLD_GUARD) == 1, f"guard: {src.count(OLD_GUARD)}"
    assert "_work_session_is_progressing" not in src
    assert "import re" in src, "autopilot.py has no re import"

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak4"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_CONSTS, NEW_CONSTS)
    src = src.replace(ANCHOR, HELPER)
    src = src.replace(OLD_GUARD, NEW_GUARD)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_budget_extension.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_budget_extension.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
