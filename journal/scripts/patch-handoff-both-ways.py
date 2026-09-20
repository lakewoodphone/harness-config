#!/usr/bin/env python3
"""Widen the terminal hand-off: ask_owner is not the only way a session stops.

Session 75409 (2026-09-14) is the evidence, and it is the second time the same
mistake appeared. Task #25105 (pay ~$70 DHL duty, spend owner-gated) ran:

  [ACTIONS: 2 (list_tasks, schedule_reminder)]   [TOOL-RESULTS-FED: 776c]
  [ACTIONS: 2 (list_tasks, save_memory)]         [TOOL-RESULTS-FED: 776c]
  [ACTIONS: 1 (update_task)]                     [TOOL-RESULTS-FED: 212c]
  "I'll close this as blocked-on-owner since I cannot make progress"
  -> failed, [STEP_BUDGET_EXHAUSTED ... without [WORK_DONE]]

It never called ask_owner. The model deliberately avoids it -- there is an SMS ban
and a don't-spam norm -- so `update_task(status=blocked)` was the only way it had to
say "I am finished and cannot proceed". The previous fix keyed on ask_owner alone,
so a correct hand-off expressed the other way still burned the budget and was
recorded as a failure.

The lesson is the same one written into the decision doc: a terminal condition must
be derived from what happened, not from one blessed action name. Detect both, and
accept the action dict whether its params are flat or nested, because that shape is
not documented and I would rather not depend on it silently.
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

# ── 1. the helper, beside the other action helpers ─────────────────────────
ANCHOR = "    @classmethod\n    def _actions_are_read_only(cls, actions: list[Any]) -> bool:"

HELPER = '''    # Ways a session can legitimately reach the end of what it is allowed to do.
    _HANDOFF_ACTIONS = frozenset({"ask_owner"})
    _HANDOFF_TASK_STATUSES = frozenset(
        {"blocked", "waiting", "needs_owner", "blocked_on_owner"}
    )

    @classmethod
    def _handoff_action(cls, actions: list[Any], results: list[Any]) -> str:
        """Name the action by which a session legitimately stopped, else "".

        Two ways a session can hit the end of its authority:
          * it queued the decision with `ask_owner`;
          * it marked its own task blocked -- which is what session 75409 did
            instead, because the model deliberately avoids ask_owner (SMS ban,
            and a norm against spamming the owner) and had no other way to say
            "I am finished and cannot proceed".

        Both are observable in the action results, which is the whole point: a
        terminal condition must not depend on a token the prompt taught the model
        to write, nor on one blessed action name.

        The action dict is accepted with params flat or nested: that shape is not
        documented anywhere, and guessing it would be exactly the kind of silent
        assumption this codebase keeps getting bitten by.
        """
        for action, result in zip(actions or [], results or []):
            if not getattr(result, "success", False) or not isinstance(action, dict):
                continue
            name = str(action.get("_action") or action.get("name") or "").strip()
            nested = action.get("params")
            params = nested if isinstance(nested, dict) else {}
            status = (
                str(action.get("status") or params.get("status") or "").strip().lower()
            )
            if name in cls._HANDOFF_ACTIONS:
                return name
            if name in ("update_task", "update_goal", "close_task"):
                if status in cls._HANDOFF_TASK_STATUSES:
                    return f"{name}({status})"
        return ""

    @classmethod
    def _actions_are_read_only(cls, actions: list[Any]) -> bool:'''

# ── 2. use it in the loop ─────────────────────────────────────────────────
OLD_COND = '''                    if any(
                        getattr(r, "success", False)
                        and str(getattr(r, "action", "")) == "ask_owner"
                        for r in results
                    ):'''

NEW_COND = '''                    _handoff = self._handoff_action(actions, results)
                    if _handoff:'''

OLD_MARKER = '''                            output_append=(
                                "[BLOCKED-ON-OWNER: the decision was handed to the "
                                "owner, so the session ends here by design rather "
                                "than restating it until the step budget runs out]"
                            ),'''

NEW_MARKER = '''                            output_append=(
                                "[BLOCKED-ON-OWNER: the session reached the end of "
                                "what it is allowed to do via "
                                f"{_handoff}; it ends here by design rather than "
                                "restating the situation until the step budget "
                                "runs out]"
                            ),'''

TEST = '''"""A session that hands off correctly must not be graded a failure.

Two live sessions on 2026-09-14, both on task #25105 (pay ~$70 DHL duty, spend
owner-gated). 75408 called ask_owner and then failed at 5/5 for lacking [WORK_DONE].
75409 avoided ask_owner (the model does not want to spam the owner) and marked the
task blocked -- and also failed, because the terminal condition knew only ask_owner.
"""

from app.autopilot import AutopilotController
from app.chat_action_parsing import ActionResult


def _handoff(actions, results):
    return AutopilotController._handoff_action(actions, results)


def test_ask_owner_completes(tmp_path=None):
    a = [{"name": "ask_owner", "params": {"question": "pay the duty?"}}]
    r = [ActionResult("ask_owner", True, "queued", {})]
    assert _handoff(a, r) == "ask_owner"


def test_update_task_blocked_completes_with_nested_params():
    """Session 75409's actual shape: it marked the task blocked."""
    a = [{"name": "update_task", "params": {"task_id": "25105", "status": "blocked"}}]
    r = [ActionResult("update_task", True, "updated", {})]
    assert _handoff(a, r) == "update_task(blocked)"


def test_update_task_blocked_completes_with_flat_params():
    """The same intent, written the other way, must not silently do nothing."""
    a = [{"_action": "update_task", "task_id": "25105", "status": "blocked"}]
    r = [ActionResult("update_task", True, "updated", {})]
    assert _handoff(a, r) == "update_task(blocked)"


def test_a_failed_action_is_not_a_handoff():
    a = [{"name": "update_task", "params": {"status": "blocked"}}]
    r = [ActionResult("update_task", False, "permission denied", {})]
    assert _handoff(a, r) == ""


def test_ordinary_task_updates_are_not_terminal():
    """Progress updates must not end a session early."""
    for status in ("in_progress", "done", "", "open"):
        a = [{"name": "update_task", "params": {"status": status}}]
        r = [ActionResult("update_task", True, "ok", {})]
        assert _handoff(a, r) == "", status


def test_no_actions_no_handoff():
    assert _handoff([], []) == ""
    assert _handoff(None, None) == ""
'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    assert src.count(ANCHOR) == 1, f"helper anchor: {src.count(ANCHOR)}"
    assert src.count(OLD_COND) == 1, f"condition: {src.count(OLD_COND)}"
    assert src.count(OLD_MARKER) == 1, f"marker: {src.count(OLD_MARKER)}"
    assert src.count("_handoff_action") == 0

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak3"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(ANCHOR, HELPER)
    src = src.replace(OLD_COND, NEW_COND)
    src = src.replace(OLD_MARKER, NEW_MARKER)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_handoff_is_terminal.py").write_text(TEST, encoding="utf-8")
    print("wrote tests/test_handoff_is_terminal.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
