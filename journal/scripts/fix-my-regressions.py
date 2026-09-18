#!/usr/bin/env python3
"""Repair the regressions my own changes caused, found by running the FULL suite.

I had been running only the test files I wrote. The full suite showed 8 failures in
tests/test_work_mode_action_syntax.py and 1 in tests/test_work_session_stops_reading.py
that are unambiguously mine.

A. `_build_work_prompt` began calling `self._consecutive_readonly_steps(...)`. That file's
   tests build the subject with `types.SimpleNamespace`, which has no such method, so
   eight prompt tests died with AttributeError. The prompt needs the CLASS's logic, not
   instance state, so it should call the class explicitly -- which also removes a hidden
   requirement that every stub carry a method.

B. tests/test_work_session_stops_reading.py asserts on SOURCE TEXT: that
   `_process_work_queue` contains `self._readonly_steps = 0`. I deleted that counter
   deliberately (it reset every tick, so the nudge it fed could never fire -- P136), so the
   assertion encodes a mechanism that no longer exists. Updated to assert the replacement
   mechanism, keeping the test's intent: the read-only count must survive across ticks.
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

OLD_CALL = "        readonly = self._consecutive_readonly_steps(accumulated_output)"
NEW_CALL = (
    "        # Called on the class, not on self: the prompt needs this logic and not any\n"
    "        # instance state, and several tests build the subject as a bare\n"
    "        # SimpleNamespace, which would not carry the method.\n"
    "        readonly = AutopilotController._consecutive_readonly_steps(accumulated_output)"
)

OLD_TEST_1 = '''    def test_the_loop_counts_read_only_steps(self):
        source = inspect.getsource(autopilot_module.AutopilotController._process_work_queue)
        assert "_actions_are_read_only(actions)" in source
        assert "self._readonly_steps = 0" in source'''

NEW_TEST_1 = '''    def test_the_read_only_count_survives_across_ticks(self):
        """The count comes from persisted step markers, not a per-tick counter.

        The counter this loop used to hold was reset at the top of every tick, and
        because the work queue executes one step per tick it could never reach the
        threshold gating the nudge -- so the nudge had never fired in production
        (journal P136). Asserting the old source text pinned a mechanism that could not
        work; assert the one that does.
        """
        loop_source = inspect.getsource(
            autopilot_module.AutopilotController._process_work_queue
        )
        assert "self._readonly_steps" not in loop_source
        prompt_source = inspect.getsource(
            autopilot_module.AutopilotController._build_work_prompt
        )
        assert "_consecutive_readonly_steps(accumulated_output)" in prompt_source'''

OLD_TEST_2 = '''    def test_the_two_corrections_are_independent(self):
        source = inspect.getsource(autopilot_module.AutopilotController._build_work_prompt)
        assert "_dropped_tag_steps" in source, "the tag correction must survive"
        assert "_readonly_steps" in source'''

NEW_TEST_2 = '''    def test_the_two_corrections_are_independent(self):
        source = inspect.getsource(autopilot_module.AutopilotController._build_work_prompt)
        assert "_dropped_tag_steps" in source, "the tag correction must survive"
        assert "_consecutive_readonly_steps" in source'''


def main() -> int:
    ap = pathlib.Path("app/autopilot.py")
    src = ap.read_text(encoding="utf-8")
    t = pathlib.Path("tests/test_work_session_stops_reading.py")
    tsrc = t.read_text(encoding="utf-8")

    assert src.count(OLD_CALL) == 1, f"prompt call: {src.count(OLD_CALL)}"
    assert tsrc.count(OLD_TEST_1) == 1, f"test 1: {tsrc.count(OLD_TEST_1)}"
    assert tsrc.count(OLD_TEST_2) == 1, f"test 2: {tsrc.count(OLD_TEST_2)}"

    for rel in ("app/autopilot.py", "tests/test_work_session_stops_reading.py"):
        backup = BACKUPS / f"{pathlib.Path(rel).name}.{STAMP}.bak9"
        if not backup.exists():
            shutil.copy(rel, backup)

    ap.write_text(src.replace(OLD_CALL, NEW_CALL), encoding="utf-8")
    t.write_text(tsrc.replace(OLD_TEST_1, NEW_TEST_1).replace(OLD_TEST_2, NEW_TEST_2),
                 encoding="utf-8")
    print("patched app/autopilot.py and tests/test_work_session_stops_reading.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
