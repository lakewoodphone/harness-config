#!/usr/bin/env python3
"""Bound the budget extension, because more steps did not buy a better outcome.

MEASURED, secratary 2026-09-14/15, session 75415 (task #25106): the extension fired
correctly and repeatedly, total_steps 5 -> 8 -> 11 -> 14 -> 15, and the session still
FAILED at 15/15 -- then the task was re-claimed immediately. Before the extension this
shape cost 5 steps and failed; now it costs 15 and fails.

The extension's mechanical behaviour is verified and wanted: a session genuinely a step
or two short should get that room (75411 completed in 4 of 5; the pipeline task #25118
did its mutating work at steps 4 and 5 and needed one more). What is not wanted is
turning a 5-step failure into a 15-step failure.

So cap the NUMBER of extensions at 2, which is enough to cross a real 5-step boundary
(worst case 5 + 3 + 3 = 11) while cutting the cost of a stuck session by a quarter. The
count is read from the persisted [BUDGET-EXTENDED:] markers -- the same source of truth
principle as the progress test -- so it survives restarts and needs no new state.

The stronger fix, deliberately NEXT and not now: the progress test extends when the last
steps contain any mutating action, and update_task/save_memory/schedule_reminder loops
satisfy that while advancing nothing. Capping first is the cheap, measurable half; do not
stack a new progress definition on top before measuring the cap.
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

OLD_CONST = "    _WORK_STEP_EXTENSION = 3"
NEW_CONST = """    _WORK_STEP_EXTENSION = 3
    # Enough to cross a real step boundary, not enough to turn a 5-step failure into a
    # 15-step one. Measured: session 75415 extended to the 15-step cap and still failed.
    _WORK_MAX_EXTENSIONS = 2"""

OLD_GUARD = """        if steps_taken < total_steps:
            return total_steps
        if total_steps >= self._WORK_ABSOLUTE_MAX_STEPS:
            return total_steps
        if not self._work_session_is_progressing(accumulated_output):
            return total_steps"""

NEW_GUARD = """        if steps_taken < total_steps:
            return total_steps
        if total_steps >= self._WORK_ABSOLUTE_MAX_STEPS:
            return total_steps
        # Counted from the persisted markers, so it survives a restart and needs no
        # new state: one [BUDGET-EXTENDED:] line is written per extension.
        if (accumulated_output or "").count("[BUDGET-EXTENDED:") >= self._WORK_MAX_EXTENSIONS:
            return total_steps
        if not self._work_session_is_progressing(accumulated_output):
            return total_steps"""

TEST = '''"""The budget extension must be bounded.

Session 75415 (task #25106) extended 5 -> 8 -> 11 -> 14 -> 15 and still failed, then the
task was re-claimed. Before the extension that shape cost 5 steps; it now cost 15. The
extension is verified mechanically and is wanted for a session genuinely one or two steps
short -- it is not wanted as a way to spend three times as much failing.
"""

from app.autopilot import AutopilotController as AC
from app.config import settings as _settings

ACTING = "Step 1: x [ACTIONS: 1 (update_task)]\\n"


def _ap():
    ap = AC.__new__(AC)
    ap._settings = _settings
    return ap


def _extend(log, total=5, steps=5):
    calls = []
    got = _ap()._maybe_extend_work_session_budget(
        steps_taken=steps, total_steps=total, accumulated_output=log, session_id=1,
        update_work_session=lambda **kw: calls.append(kw), proactive_actions=[],
    )
    return got, calls


def test_a_session_with_no_extension_yet_may_extend():
    got, calls = _extend(ACTING)
    assert got == 8 and calls


def test_one_previous_extension_may_extend_again():
    log = ACTING + "[BUDGET-EXTENDED: 5 -> 8 steps.]\\n"
    got, calls = _extend(log, total=8, steps=8)
    assert got == 11 and calls


def test_two_previous_extensions_stop_it():
    """The cap: worst case is 5 + 3 + 3 = 11 steps, not 15."""
    log = (ACTING
           + "[BUDGET-EXTENDED: 5 -> 8 steps.]\\n"
           + "[BUDGET-EXTENDED: 8 -> 11 steps.]\\n")
    got, calls = _extend(log, total=11, steps=11)
    assert got == 11, got
    assert calls == [], "extended past the cap"


def test_the_cap_is_small_enough_to_matter():
    worst = AC._WORK_MAX_STEPS + AC._WORK_MAX_EXTENSIONS * AC._WORK_STEP_EXTENSION
    assert worst <= 11, worst
    assert AC._WORK_MAX_EXTENSIONS >= 1
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    assert src.count(OLD_CONST) == 1, f"const: {src.count(OLD_CONST)}"
    assert src.count(OLD_GUARD) == 1, f"guard: {src.count(OLD_GUARD)}"
    assert "_WORK_MAX_EXTENSIONS" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak8"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_CONST, NEW_CONST, 1)
    src = src.replace(OLD_GUARD, NEW_GUARD)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_budget_cap.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_budget_cap.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
