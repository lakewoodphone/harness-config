#!/usr/bin/env python3
"""Make the reconnaissance nudge able to fire, by counting from persisted markers.

The nudge in `_build_work_prompt` prepends "STOP SEARCHING - N consecutive steps only
READ things" when `self._readonly_steps >= 2`. That counter is reset to 0 at the top of
every `_process_work_queue` call, and `autopilot_work_queue_poll_max_steps` is 1 -- so
each tick runs a single step and the counter can never exceed 1. Measured 2026-09-14:
the nudge has never fired in production.

Its value is small (an earlier measurement showed the model ignores the nudge when it
does appear), but a signal that cannot fire is worse than no signal, because it reads as
enforcement. The same fact is already available from the persisted step markers, which
is what `_work_session_is_progressing` reads, so this removes the duplicate source.

A `[NO-ACTION:]` step breaks the streak rather than counting as reconnaissance: a step
that did nothing is a different failure and the two corrections should stay independent.
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

HELPER = '''    @classmethod
    def _consecutive_readonly_steps(cls, accumulated_output: str) -> int:
        """How many trailing steps only looked at things.

        Derived from the PERSISTED step markers, not from a counter: the counter this
        replaced was reset at the top of every tick, and since the queue runs one step
        per tick it could never reach 2, so the STOP SEARCHING nudge never fired in
        production. A step with no actions at all breaks the streak -- doing nothing is
        a different failure from exploring, and the two corrections stay independent.
        """
        tokens = re.findall(
            r"\\[ACTIONS:\\s*\\d+\\s*\\(([^)]*)\\)\\]|\\[NO-ACTION:",
            accumulated_output or "",
        )
        count = 0
        for token in reversed(tokens):
            if not token:
                break  # a [NO-ACTION:] step
            names = [n.strip() for n in token.split(",") if n.strip()]
            if not names or not all(cls._action_name_is_read_only(n) for n in names):
                break
            count += 1
        return count

    @classmethod
    def _work_session_is_progressing(cls, accumulated_output: str) -> bool:'''

OLD_INIT = (
    "        # And how many consecutive steps did reconnaissance only.\n"
    "        self._readonly_steps = 0"
)
NEW_INIT = (
    "        # The reconnaissance count is derived from the persisted step markers\n"
    "        # (see _consecutive_readonly_steps); there is no per-tick counter."
)

OLD_BLOCK = '''                if actions:
                    if self._actions_are_read_only(actions):
                        self._readonly_steps = (
                            int(getattr(self, "_readonly_steps", 0) or 0) + 1
                        )
                    else:
                        self._readonly_steps = 0
                accumulated_output += step_marker + "\\n"'''
NEW_BLOCK = '''                accumulated_output += step_marker + "\\n"'''

OLD_READ = '        readonly = int(getattr(self, "_readonly_steps", 0) or 0)'
NEW_READ = "        readonly = self._consecutive_readonly_steps(accumulated_output)"

TEST = '''"""The reconnaissance nudge must be able to fire.

It is gated on a count of consecutive read-only steps, and the counter that fed it was
reset at the top of every tick. Since the queue executes one step per tick, the count
could never reach the threshold of 2 -- measured 2026-09-14, the nudge had never fired
in production. The count now comes from the persisted step markers.
"""

from app.autopilot import AutopilotController as AC
from app.config import settings as _settings


def _step(names):
    return f"[ACTIONS: {len(names)} ({', '.join(names)})] [TOOL-RESULTS-FED: 100c]"


def test_counts_trailing_read_only_steps():
    text = "\\n".join([_step(["gmail_list"]), _step(["ha_states", "qb_status"])])
    assert AC._consecutive_readonly_steps(text) == 2


def test_a_mutating_step_resets_the_count():
    text = "\\n".join([_step(["gmail_list"]), _step(["update_task"])])
    assert AC._consecutive_readonly_steps(text) == 0


def test_only_the_trailing_streak_counts():
    text = "\\n".join(
        [_step(["gmail_list"]), _step(["close_task"]), _step(["ha_states"])]
    )
    assert AC._consecutive_readonly_steps(text) == 1


def test_a_step_with_no_actions_breaks_the_streak():
    text = f"{_step(['ha_states'])}\\n[NO-ACTION: reply=40c cleaned=40c]"
    assert AC._consecutive_readonly_steps(text) == 0


def test_nothing_recorded_means_nothing_counted():
    assert AC._consecutive_readonly_steps("") == 0
    assert AC._consecutive_readonly_steps(None) == 0


def _autopilot_stub():
    ap = AC.__new__(AC)
    ap._dropped_tag_steps = 0
    ap._agent_id = "test-agent"
    ap._settings = _settings
    return ap


def test_two_read_only_steps_actually_put_the_nudge_in_the_prompt():
    """The property that was broken: the nudge never reached a prompt."""
    ap = _autopilot_stub()
    session = {"id": 1, "title": "t", "total_steps": 5}
    context = {"payload": {}, "job_type": "general"}
    log = "\\n".join([_step(["gmail_list"]), _step(["ha_states"])]) + "\\n"
    prompt = ap._build_work_prompt(session, context, log, 3)
    assert "STOP SEARCHING" in prompt, prompt[:400]


def test_a_single_read_only_step_does_not_nag():
    ap = _autopilot_stub()
    session = {"id": 1, "title": "t", "total_steps": 5}
    context = {"payload": {}, "job_type": "general"}
    log = _step(["gmail_list"]) + "\\n"
    prompt = ap._build_work_prompt(session, context, log, 2)
    assert "STOP SEARCHING" not in prompt
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    anchor = "    @classmethod\n    def _work_session_is_progressing(cls, accumulated_output: str) -> bool:"
    assert src.count(anchor) == 1, f"anchor: {src.count(anchor)}"
    assert src.count(OLD_INIT) == 1, f"init: {src.count(OLD_INIT)}"
    assert src.count(OLD_BLOCK) == 1, f"counter block: {src.count(OLD_BLOCK)}"
    assert src.count(OLD_READ) == 1, f"prompt read: {src.count(OLD_READ)}"
    assert "_consecutive_readonly_steps" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak6"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(anchor, HELPER)
    src = src.replace(OLD_INIT, NEW_INIT)
    src = src.replace(OLD_BLOCK, NEW_BLOCK)
    src = src.replace(OLD_READ, NEW_READ)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    # the counter must be gone entirely, or there are two sources of truth again
    assert "_readonly_steps" not in src, "a _readonly_steps reference survived"
    print("confirmed: _readonly_steps is gone")

    pathlib.Path("tests/test_recon_nudge.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_recon_nudge.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
