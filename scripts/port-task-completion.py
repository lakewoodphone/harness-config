"""Hand-port task-based session completion into the authority's autopilot.py.

Gated: every anchor must match EXACTLY ONCE or nothing is written.

This is the largest fix of the audit: 664 of 679 failed sessions had their task
marked `done`, so the work finished and the session was scored as failure, because
completion keyed only on the `[WORK_DONE]` token.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-task-completion.py.pre")

METHOD_OLD = '''        if actions:
            return 0
        from app.chat_actions import ACTION_PATTERN

        return len(ACTION_PATTERN.findall(reply or ""))

    def _close_unfinished_work_session(
'''

METHOD_NEW = '''        if actions:
            return 0
        from app.chat_actions import ACTION_PATTERN

        return len(ACTION_PATTERN.findall(reply or ""))

    def _task_is_closed(self, task_id: Any | None) -> bool:
        """Whether the task's OWN status says the work is complete.

        Measured on this host 2026-09-14: of 679 failed work sessions that had a
        task, 664 (97.8%) had the task marked `done`. The work finished and the
        session was recorded as a failure anyway, because completion was judged only
        by the model emitting a [WORK_DONE] token.

        The task row is the authoritative statement of whether the work is done; the
        token is a convention the model does not reliably follow.
        """
        if task_id is None:
            return False
        try:
            # get_task is imported locally in _process_work_queue, not at module
            # level -- referring to it as a global raises NameError, and a bare
            # `except Exception: return False` would turn that into "the work is not
            # complete", a plausible answer and therefore an invisible one.
            from app.database import TASK_COMPLETED_STATUSES, get_task

            t = get_task(db_url=self._db_url, task_id=int(task_id))
        except Exception as exc:  # noqa: BLE001 - a read failure must not complete
            logger.warning(
                "could not read task %s while judging session completion: %s",
                task_id,
                exc,
            )
            return False
        status = str((t or {}).get("status") or "").strip().lower()
        return status in TASK_COMPLETED_STATUSES

    def _close_unfinished_work_session(
'''

BLOCK_OLD = '''                # Check if the LLM signaled completion
                if "[WORK_DONE]" in reply:
'''

BLOCK_NEW = '''                # -- Completion judged by the record, not by a token ----------
                # 664 of 679 failed sessions on this host had their task marked
                # `done`: the work finished and the session was failed anyway,
                # because completion keyed only on [WORK_DONE]. If this step
                # executed an action and the task's own status now says it is
                # closed, the session is complete -- the token is a convention, the
                # task row is the record.
                if actions and task_id_ctx is not None and self._task_is_closed(task_id_ctx):
                    if artifact_required and not self._work_output_has_completion_artifact(
                        accumulated_output
                    ):
                        # The artifact gate still applies: a closed task without the
                        # required evidence is blocked, not complete.
                        pass
                    else:
                        update_work_session(
                            db_url=self._db_url,
                            session_id=session_id,
                            status="completed",
                            progress_pct=100,
                            output_append=(
                                "[COMPLETED: the task itself is closed; no "
                                "[WORK_DONE] token was required]"
                            ),
                        )
                        if job_id:
                            try:
                                complete_job(
                                    db_url=self._db_url,
                                    job_id=job_id,
                                    result={
                                        "output": accumulated_output[-5000:],
                                        "reason": "task_closed",
                                    },
                                )
                            except Exception:
                                pass
                        proactive_actions.append(
                            f"Work completed: session {session_id} closed by the "
                            f"task's own status"
                        )
                        break

                # Check if the LLM signaled completion
                if "[WORK_DONE]" in reply:
'''

EDITS = [
    ("task-is-closed-method", METHOD_OLD, METHOD_NEW),
    ("completion-block", BLOCK_OLD, BLOCK_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  anchor {name!r} matched {n} time(s), need exactly 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text
    for _n, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    checks = [
        ("method defined", "def _task_is_closed(" in new),
        ("method used in loop", "_task_is_closed(task_id_ctx)" in new),
        ("task_closed reason", '"reason": "task_closed"' in new),
        ("completion marker", "the task itself is closed" in new),
        ("token path kept", '"[WORK_DONE]" in reply' in new),
        ("artifact gate kept", "artifact_required and not self._work_output_has_completion_artifact" in new),
        ("local get_task import", "from app.database import TASK_COMPLETED_STATUSES, get_task" in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"bytes: {len(text)} -> {len(new)}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
