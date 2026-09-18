#!/usr/bin/env python3
"""A successful owner hand-off is a terminal outcome, not a failure.

Session 75408 (2026-09-14) is the evidence. Task #25105 asked it to pay ~$70 of
DHL import duty, and spend is hard-gated (spend_approval_threshold=always_manual):

  Step 1: [ACTIONS: 2 (fetch_url, list_tasks)]        -- reconnaissance, fine
  Step 2: [ACTIONS: 1 (ask_owner)]                    -- the correct action
  Steps 3-5: restating that it cannot pay
  -> failed, [STEP_BUDGET_EXHAUSTED: reached planned 5/5 work steps without [WORK_DONE]]

It did the right thing and was graded a failure for it, then re-claimed, because
the loop's terminal conditions were "the task row is closed" or "the reply contains
the literal [WORK_DONE]". Neither describes "I have handed this to the only person
who can decide". A magic string cannot observe a hand-off; an action result can.

Also: make the tool-result feedback observable. It goes into accumulated_output
(which is the point -- the next prompt is built from it), but nothing recorded that
it happened, so it could not be verified from a session log. That is the difference
between a fix and an article of faith.
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

OLD_RESULTS = '''                    rendered = self._render_tool_results(results)
                    if rendered:
                        accumulated_output += f"\\n{rendered}\\n"
'''

NEW_RESULTS = '''                    rendered = self._render_tool_results(results)
                    if rendered:
                        accumulated_output += f"\\n{rendered}\\n"

                    # A successful owner hand-off ends the session. The decision
                    # belongs to the one person who can make it, and no remaining
                    # step can improve the outcome -- the session could only spend
                    # its budget restating a situation it was forbidden to change.
                    # Session 75408 (2026-09-14) did exactly that: it called
                    # ask_owner on step 2 of 5 for an owner-gated spend, then was
                    # recorded as a FAILURE for not emitting [WORK_DONE]. Terminal
                    # conditions must come from what happened, not from a token.
                    if any(
                        getattr(r, "success", False)
                        and str(getattr(r, "action", "")) == "ask_owner"
                        for r in results
                    ):
                        if task_id_ctx:
                            try:
                                update_task(
                                    db_url=self._db_url,
                                    task_id=task_id_ctx,
                                    status="blocked",
                                )
                            except Exception as exc:
                                logger.warning(
                                    "owner hand-off: could not block task %s: %s",
                                    task_id_ctx,
                                    exc,
                                )
                        update_work_session(
                            db_url=self._db_url,
                            session_id=session_id,
                            status="paused",
                            output_append=(
                                "[BLOCKED-ON-OWNER: the decision was handed to the "
                                "owner, so the session ends here by design rather "
                                "than restating it until the step budget runs out]"
                            ),
                        )
                        if job_id:
                            try:
                                complete_job(
                                    db_url=self._db_url,
                                    job_id=job_id,
                                    result={
                                        "status": "blocked_on_owner",
                                        "output": accumulated_output[-5000:],
                                    },
                                )
                            except Exception:
                                pass
                        proactive_actions.append(
                            f"Session {session_id} ended: owner decision handed off"
                        )
                        break
'''

OLD_MARKER = '''                if actions:
                    step_marker = (
                        f"\\n[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]"
                    )'''

NEW_MARKER = '''                if actions:
                    step_marker = (
                        f"\\n[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]"
                        # Record that the results were fed back, so the mechanism
                        # can be verified from the session log instead of assumed.
                        f" [TOOL-RESULTS-FED: {len(rendered)}c]"
                    )'''


def main() -> int:
    path = pathlib.Path("app/autopilot.py")
    src = path.read_text(encoding="utf-8")

    assert src.count(OLD_RESULTS) == 1, f"results block: {src.count(OLD_RESULTS)}"
    assert src.count(OLD_MARKER) == 1, f"marker block: {src.count(OLD_MARKER)}"

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak2"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(OLD_RESULTS, NEW_RESULTS)
    src = src.replace(OLD_MARKER, NEW_MARKER)
    path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    doc = pathlib.Path("docs/decisions/2026-09-14-owner-handoff-is-terminal.md")
    doc.parent.mkdir(parents=True, exist_ok=True)
    doc.write_text(
        "# A successful owner hand-off is a terminal session outcome\n\n"
        "Decided 2026-09-14 by Zabz (development decision, not an owner question).\n\n"
        "## Decision\n\n"
        "When a work session successfully executes `ask_owner`, the session ends\n"
        "immediately in status `paused` with a `[BLOCKED-ON-OWNER]` record, its job\n"
        "completes with reason `blocked_on_owner`, and the underlying task is set to\n"
        "`blocked`. It is not a failure and it is not retried with the same context.\n\n"
        "## Why\n\n"
        "Spend is hard-gated (`spend_approval_threshold=always_manual`), so a task\n"
        "like #25105 (pay ~$70 DHL import duty) can only be handed to the owner. The\n"
        "loop's terminal conditions were \"the task row is closed\" or \"the reply\n"
        "contains the literal `[WORK_DONE]`\". Neither can observe a hand-off, so\n"
        "session 75408 called `ask_owner` on step 2 of 5, spent steps 3-5 restating\n"
        "the situation, and was recorded as a failure for lacking a token it had no\n"
        "reason to emit -- then re-claimed.\n\n"
        "## Consequence\n\n"
        "A terminal condition must be derived from what happened, not from a string\n"
        "the prompt taught the model to write. The same reasoning applies to any\n"
        "future terminal state: make it observable in an action result.\n",
        encoding="utf-8",
    )
    print("wrote docs/decisions/2026-09-14-owner-handoff-is-terminal.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
