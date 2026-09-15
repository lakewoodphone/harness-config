#!/usr/bin/env python3
"""A repeated mutating call is not progress: measure the run, not the verb.

MEASURED on secratary 2026-09-15, from every session that earned a budget extension:

  75415  15/15 ext=4  steps 4-6 [update_task, schedule_reminder] x3,
                      steps 7-15 [list_tasks, update_task] x9      -> failed
  75419  11/11 ext=2  steps 5-11 [update_task] x7                  -> failed
  75426  11/11 ext=2  steps 5-11 [update_task] x7                  -> failed

`_work_session_is_progressing` credited each of those, because a repeated `update_task` is
still a non-read-only action. So the extension test added earlier the same night -- the one
meant to reward real work -- could be satisfied forever by one mutating call in a loop, and
75415 burned all fifteen steps to fail.

WHAT SEPARATES WORKING FROM SPINNING is not the action, it is the run length. The two sessions
that genuinely COMPLETED never repeated an action signature more than twice:

  75418  completed 9/11  system_health, system_health, update_task, system_health,
                         update_task, system_health, update_task, close_task
  75427  completed 11/11 ha_states, ha_states, save_memory, update_task, ha_states,
                         ha_states, update_task, update_task, update_task, update_task

So: refuse the extension when the last _PROGRESS_REPEAT_RUN step signatures are all identical,
and otherwise keep the existing rule. Both conditions read the persisted step markers, so
nothing new has to be stored and the judgement survives a restart.

This is deliberately a small change to one predicate rather than a new "effect" mechanism: an
effect-based rule (did the task row change?) was the obvious design and it would have BROKEN
75418, whose mid-session update_task calls may not alter any task field, so it would have lost
the extension that let it finish. The observed difference between a completing session and a
spinning one is the run, and that is what this measures.
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

OLD_CONST = "    _PROGRESS_STEP_WINDOW = 3"
NEW_CONST = """    _PROGRESS_STEP_WINDOW = 3
    # Consecutive identical action signatures that mean stagnation rather than work.
    # Measured: the spinning sessions ran one signature 7 to 9 times; the two that
    # completed never ran one more than twice.
    _PROGRESS_REPEAT_RUN = 3"""

OLD_BODY = '''        markers = re.findall(
            r"\\[ACTIONS:\\s*\\d+\\s*\\(([^)]*)\\)\\]", accumulated_output or ""
        )
        if not markers:
            return False
        for names in markers[-cls._PROGRESS_STEP_WINDOW:]:'''

NEW_BODY = '''        markers = re.findall(
            r"\\[ACTIONS:\\s*\\d+\\s*\\(([^)]*)\\)\\]", accumulated_output or ""
        )
        if not markers:
            return False

        # Stagnation: the same signature repeated. A repeated update_task is still a
        # mutating action, which is how 75415 earned four extensions over nine identical
        # steps and failed at 15/15. The sessions that completed never repeated a
        # signature more than twice, so the run length is the honest discriminator.
        if len(markers) >= cls._PROGRESS_REPEAT_RUN:
            tail = {m.strip().lower() for m in markers[-cls._PROGRESS_REPEAT_RUN:]}
            if len(tail) == 1:
                return False

        for names in markers[-cls._PROGRESS_STEP_WINDOW:]:'''

TEST = '''"""A repeated mutating call must not earn budget extensions.

Measured on secratary 2026-09-15, from every session that earned an extension: 75415 ran
[list_tasks, update_task] for NINE consecutive steps (4 extensions, failed at 15/15); 75419
and 75426 each ran [update_task] seven times. The two sessions that genuinely completed never
repeated a signature more than twice.
"""

import pytest

from app.autopilot import AutopilotController as AC


def _steps(sigs):
    return "\\n".join(f"[ACTIONS: {len(s.split(','))} ({s})] [TOOL-RESULTS-FED: 100c]"
                     for s in sigs)


def test_the_nine_identical_steps_of_75415_are_not_progress():
    """The exact shape that burned four extensions."""
    sigs = ["repo_read_file, list_tasks"] * 3 + ["list_tasks, update_task"] * 9
    assert AC._work_session_is_progressing(_steps(sigs)) is False


def test_seven_identical_update_tasks_are_not_progress():
    sigs = ["ha_entity, ha_entity", "update_task"] * 1 + ["update_task"] * 6
    assert AC._work_session_is_progressing(_steps(sigs)) is False


def test_the_completing_shape_of_75418_still_counts_as_progress():
    """Alternating check/record work must keep earning room."""
    sigs = ["system_health", "system_health", "update_task", "system_health",
            "update_task", "system_health", "update_task"]
    assert AC._work_session_is_progressing(_steps(sigs)) is True


def test_the_completing_shape_of_75427_still_counts_as_progress():
    sigs = ["ha_states", "ha_states", "save_memory", "update_task", "ha_states",
            "ha_states", "update_task", "update_task"]
    assert AC._work_session_is_progressing(_steps(sigs)) is True


def test_two_identical_steps_are_not_yet_stagnation():
    """The guard needs a run, not a pair: some genuine steps repeat once."""
    sigs = ["system_health", "update_task", "update_task"]
    assert AC._work_session_is_progressing(_steps(sigs)) is True


def test_pure_reconnaissance_is_still_not_progress():
    sigs = ["gmail_list", "ha_states", "qb_status", "list_tasks"]
    assert AC._work_session_is_progressing(_steps(sigs)) is False


def test_no_markers_is_not_progress():
    assert AC._work_session_is_progressing("") is False
    assert AC._work_session_is_progressing("Step 1: prose only\\n") is False


def test_the_stagnation_run_is_small_enough_to_matter():
    assert 2 <= AC._PROGRESS_REPEAT_RUN <= 4
'''


def main() -> int:
    ap = pathlib.Path("app/autopilot.py")
    src = ap.read_text(encoding="utf-8")

    assert src.count(OLD_CONST) == 1, f"const: {src.count(OLD_CONST)}"
    assert src.count(OLD_BODY) == 1, f"body: {src.count(OLD_BODY)}"
    assert "_PROGRESS_REPEAT_RUN" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak12"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_CONST, NEW_CONST, 1)
    src = src.replace(OLD_BODY, NEW_BODY)
    ap.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_progress_not_repetition.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_progress_not_repetition.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
