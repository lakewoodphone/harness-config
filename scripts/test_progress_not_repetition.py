"""A repeated mutating call must not earn budget extensions.

THE EVIDENCE IS A REPLAY, NOT THESE FIXTURES. Measured on secratary 2026-09-15 by replaying
every extension decision against the real session logs:

    session  old (run=3)   new (run=2)   outcome
    75415    11 steps      8 steps       failed either way
    75419     8 steps      8 steps       failed either way
    75426     8 steps      8 steps       failed either way
    75418    11 steps     11 steps       COMPLETED -- preserved exactly
    75427    11 steps     11 steps       COMPLETED -- preserved exactly

The predicate reads the persisted step markers, so WHICH markers a real log contains decides the
answer. Twice while writing these tests I transcribed a session's actions by hand and got a
sequence the real log does not contain (a step can produce no [ACTIONS:] marker at all), which
produced a failing test for a predicate that was behaving correctly. So these fixtures are
deliberately minimal and synthetic: they pin the RULE, and the replay above is the evidence for
the CONSTANT.
"""

import pytest

from app.autopilot import AutopilotController as AC


def _steps(sigs):
    return "\n".join(f"[ACTIONS: {len(s.split(','))} ({s})] [TOOL-RESULTS-FED: 100c]"
                     for s in sigs)


def _at_decision_point(sigs, upto):
    """Evaluate as the loop does: at a decision, on the log as it stood THEN.

    Evaluating a predicate over a session's FINAL log answers a different question -- trailing
    repeats that came after the last extension say nothing about whether that extension was
    earned. That mistake produced a false alarm in this very file.
    """
    return AC._work_session_is_progressing(_steps(sigs[:upto]))


def test_the_nine_identical_steps_of_75415_are_not_progress():
    """The shape that collected four extensions and failed at 15/15."""
    sigs = ["repo_read_file, list_tasks"] * 3 + ["list_tasks, update_task"] * 9
    assert AC._work_session_is_progressing(_steps(sigs)) is False


def test_repeated_identical_mutating_steps_are_not_progress():
    assert AC._work_session_is_progressing(_steps(["update_task"] * 6)) is False


def test_alternating_check_and_record_work_still_counts_as_progress():
    """The completing shape: no two consecutive signatures identical."""
    sigs = ["system_health", "update_task", "system_health", "update_task"]
    assert _at_decision_point(sigs, 4) is True
    assert AC._work_session_is_progressing(_steps(sigs)) is True


def test_the_final_log_and_the_decision_point_can_disagree():
    """Trailing repeats after the last extension are not evidence about it."""
    sigs = ["system_health", "update_task", "system_health", "update_task", "update_task"]
    assert _at_decision_point(sigs, 4) is True      # the decision that mattered
    assert AC._work_session_is_progressing(_steps(sigs)) is False   # the final snapshot


def test_pure_reconnaissance_is_still_not_progress():
    sigs = ["gmail_list", "ha_states", "qb_status", "list_tasks"]
    assert AC._work_session_is_progressing(_steps(sigs)) is False


def test_a_single_mutating_step_earns_room():
    assert AC._work_session_is_progressing(_steps(["list_tasks, save_memory"])) is True


def test_no_markers_is_not_progress():
    assert AC._work_session_is_progressing("") is False
    assert AC._work_session_is_progressing("Step 1: prose only\n") is False


def test_the_repeat_run_is_set_from_measured_evidence():
    """2, chosen by replay: it saves 3 further steps with both completions intact.

    The evidence base is seven sessions. If completions ever drop, raise this and re-run the
    replay rather than guessing -- the comment on the constant says so too.
    """
    assert AC._PROGRESS_REPEAT_RUN == 2
