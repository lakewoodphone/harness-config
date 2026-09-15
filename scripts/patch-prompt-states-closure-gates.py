#!/usr/bin/env python3
"""Put the task-closure rules in the surface the work sessions actually read.

MEASURED on secratary 2026-09-15, and this is the thrash generator behind the spinners.

Task #25163 ran twice with the same task and the same budget:
  75426  FAILED 11/11  steps 5-11 = [update_task] x7, each one refused, until the budget died
  75427  COMPLETED 11/11  same work, and it says why it got out:
        "The prior update_task calls failed because the task is only ~1h old and needs
         force='true'. Let me close it properly with force."

Two gates in `_exec_update_task` refuse a closure, and neither is discoverable from the work
prompt:

  * age < 48h                       -> "Cannot close tasks < 48h old without force='true'"
  * status in_progress and age < 7d -> "Cannot close in-progress tasks less than 7 days old
                                        without force='true'"

Essentially EVERY task these sessions work is younger than 48 hours, and a task being worked
is in_progress, so both gates apply to the normal case. A refused update_task still looks like
a mutating action, which is why these sessions earned extensions while retrying it.

THE RULE ALREADY EXISTS, IN THE WRONG PLACE. The individual `close_task` TOOL description says
it plainly: "tasks < 48h old OR in_progress tasks < 7 days old cannot be closed unless
force='true' is passed. Always pass force='true' when closing stale, duplicate, or superseded
tasks regardless of age." The work prompt -- the surface these sessions use, and the one that
tells them to call update_task(status="done") -- does not mention it at all. So the model is
told to use the gated path by instructions that omit the gate.

FIX: state the rule in the work prompt, including the part that stops the loop -- repeating the
call without force cannot work. No gate is relaxed: the 48h rule keeps its intent (agents were
closing tasks seconds after creating them) and the independent `_task_close_would_be_a_lie`
guard still refuses a completion whose only evidence is failure.
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

OLD = '''            "- Do NOT leave tasks open if you cannot make "
            "progress. Close or reassign them.",
            "",
        ]'''

NEW = '''            "- Do NOT leave tasks open if you cannot make "
            "progress. Close or reassign them.",
            "",
            "CLOSING IS GATED, AND THE GATE IS INVISIBLE UNLESS YOU ASK FOR IT:",
            "- update_task(status=\\"done\\") is REFUSED for a task less than 48h old, or for "
            "an in_progress task less than 7 days old, unless you also pass "
            'force: "true" -- params={"task_id": "ID", "status": "done", '
            '"force": "true"}.',
            "- CALLING IT AGAIN WITHOUT force WILL KEEP FAILING. Repeating the same call is "
            "not a way through it, and it is the single most common way these sessions run "
            "out of budget. If a close is refused, either add force or do something else.",
            "- Nearly every task you work is younger than 48h, so this applies to almost "
            'every close. For a stale, duplicate or superseded task, pass force: "true" as a '
            "matter of course.",
            "- Use force only when the work really is finished or the task really should not "
            "continue. If it is not finished, put what remains in the description and close "
            "with force rather than leaving it open for another session to attempt the same "
            "work again.",
            "",
        ]'''

TEST = '''"""The work prompt must state the closure gates the sessions actually hit.

Task #25163 ran twice: 75426 repeated a refused update_task seven times and died at 11/11;
75427 completed because it worked out that the call needs force='true' -- "the task is only
~1h old and needs force='true'". The rule was already written in the close_task TOOL
description and absent from the work prompt, which is the surface these sessions read.
"""

from app.autopilot import AutopilotController as AC
from app.config import settings as _settings


def _prompt():
    ap = AC.__new__(AC)
    ap._dropped_tag_steps = 0
    ap._agent_id = "test-agent"
    ap._settings = _settings
    return ap._build_work_prompt(
        {"id": 1, "title": "t", "total_steps": 5},
        {"payload": {}, "job_type": "general"},
        "",
        1,
    )


def test_the_prompt_names_the_force_requirement():
    p = _prompt()
    assert "force" in p
    assert "48h" in p
    assert "7 days" in p


def test_the_prompt_says_repeating_the_call_cannot_help():
    """The line that actually stops the loop: 75426 repeated it seven times."""
    p = _prompt()
    assert "KEEP FAILING" in p or "keep failing" in p


def test_the_prompt_no_longer_offers_an_unqualified_close():
    """The old instruction told them to call the gated path with no mention of the gate."""
    p = _prompt()
    assert 'force: "true"' in p
'''


def main() -> int:
    ap = pathlib.Path("app/autopilot.py")
    src = ap.read_text(encoding="utf-8")
    assert src.count(OLD) == 1, f"anchor: {src.count(OLD)}"
    assert "CLOSING IS GATED" not in src

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak14"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    ap.write_text(src.replace(OLD, NEW), encoding="utf-8")
    print("patched app/autopilot.py (work prompt)")

    pathlib.Path("tests/test_work_prompt_states_closure_gates.py").write_text(
        TEST, encoding="utf-8"
    )
    print("wrote tests/test_work_prompt_states_closure_gates.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
