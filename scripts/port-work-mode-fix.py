"""Hand-port the work-mode action-syntax fix into the authority's live
app/autopilot.py.

The live checkout is 87 commits behind origin/master, so a git patch cannot be
applied to it (verified: `git apply --3way` produced conflict markers and the
compile gate rolled it back). The regions this fix touches are textually
identical on both sides, so a deterministic exact-string port is safe -- but
every anchor must match EXACTLY ONCE or the script refuses and changes nothing.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-autopilot.py.pre")

HELPER_NEW = '''        return "blocker" in lower and "evidence" in lower

    @staticmethod
    def _dropped_action_tag_count(reply: str, actions: list[Any]) -> int:
        """Count legacy [ACTION:...] tags that were stripped without running.

        When ``assistant_legacy_action_tags_enabled`` is False (the shipped
        default) ``parse_actions()`` deletes ``[ACTION:...]`` and returns no
        actions, so a tag the model wrote executes nothing. That is silent, and
        silence is the bug: a step that only wrote a tag looks identical to a
        step that did nothing, so the session burns its budget restating itself
        until the repetition guard fails it. Counting the dropped tags makes the
        no-op visible and lets the next step's prompt correct it.

        Measured on this host 2026-09-07..2026-09-14: 270 of 674 work-session
        failures (40%) carried [STALLED_REPEATING_OUTPUT].
        """
        if actions:
            return 0
        from app.chat_actions import ACTION_PATTERN

        return len(ACTION_PATTERN.findall(reply or ""))

    def _close_unfinished_work_session(
'''

RESET_OLD = """        current_step = steps_done  # Initialize to avoid unbound variable
        session_start = time.monotonic()
"""
RESET_NEW = """        current_step = steps_done  # Initialize to avoid unbound variable
        session_start = time.monotonic()
        # Reset per-session: how many steps emitted legacy [ACTION:...] tags
        # that this deployment silently discards (see the detector below).
        self._dropped_tag_steps = 0
"""

DETECT_OLD = """                accumulated_output += f"\\n--- Step {current_step} ---\\n" f"{cleaned}\\n"
"""
DETECT_NEW = '''                # -- Dropped-tag detector: make a silent no-op loud --------
                # assistant_legacy_action_tags_enabled is False here, so
                # parse_actions() STRIPS any [ACTION:...] tag and returns no
                # actions. A model that emits tags therefore does nothing, the
                # step still consumes budget, and the session repeats itself
                # until the repetition guard fails it. Measured on this host
                # 2026-09-07..09-14: 270 of 674 work-session failures (40%)
                # carried [STALLED_REPEATING_OUTPUT]. Silently discarding the
                # tag is what made that invisible.
                dropped_tags = self._dropped_action_tag_count(reply, actions)
                if dropped_tags:
                    self._dropped_tag_steps = (
                        int(getattr(self, "_dropped_tag_steps", 0) or 0) + 1
                    )
                    accumulated_output += (
                        f"[DROPPED-ACTION-TAGS: {dropped_tags} [ACTION:...] tag(s) "
                        f"in step {current_step} executed nothing -- the legacy tag "
                        f"syntax is disabled in this deployment]\\n"
                    )
                    proactive_actions.append(
                        f"Session {session_id} step {current_step}: "
                        f"{dropped_tags} [ACTION:] tag(s) dropped (legacy syntax off)"
                    )

                accumulated_output += f"\\n--- Step {current_step} ---\\n" f"{cleaned}\\n"
'''

PROMPT_OLD = '''            "- Use [ACTION:...] tags to take concrete actions "
            "(save_memory, create_task, update_task, github_*, "
            "repo_*, send_sms, etc).",
            "- When the work is FULLY DONE, include [WORK_DONE] " "in your response.",
            "- If you need more steps, just describe what you "
            "accomplished and what remains.",
            "- Be concrete and action-oriented.",
            "",
            "TASK COMPLETION RULES:",
            "- If you complete the task, use "
            "[ACTION:update_task|task_id=ID|status=done] AND "
            "include [WORK_DONE] in your response.",
            "- If the task is a duplicate or already handled, "
            "close it: [ACTION:close_task|task_id=ID] "
            "then [WORK_DONE].",
            "- If the task cannot be done (missing info, wrong "
            "department, no access), close it with a note: "
            "[ACTION:update_task|task_id=ID|status=done|"
            "description=Cannot execute: reason] "
            "then [WORK_DONE].",
            "- Do NOT leave tasks open if you cannot make "
            "progress. Close or reassign them.",
            "",
        ]
'''

PROMPT_NEW = '''            "- Take concrete actions by CALLING TOOLS DIRECTLY (native tool "
            "calling): execute_action, save_memory, create_task, update_task, "
            "github_*, repo_*, send_sms, etc.",
            "- Do NOT write [ACTION:...] tags. That legacy syntax is DISABLED in "
            "this deployment: any tag you write is stripped and executed by "
            "nothing, so a step whose only output is a tag has done no work.",
            "- If native tool calling is unavailable, return ONE JSON block: "
            '```assistant_response {"reply":"...","actions":[{"name":"create_task",'
            '"params":{"title":"..."}}]}```',
            "- EVERY step must contain at least one tool call, or the [WORK_DONE] "
            "signal. A step that only narrates a plan or restates the task has "
            "made no progress and will be counted against you.",
            "- When the work is FULLY DONE, include [WORK_DONE] " "in your response.",
            "- If you need more steps, describe what you ACTUALLY accomplished "
            "with tools and what remains.",
            "- Be concrete and action-oriented.",
            "",
            "TASK COMPLETION RULES:",
            "- If you complete the task, call "
            'execute_action(action="update_task", params={"task_id": "ID", '
            '"status": "done"}) AND include [WORK_DONE] in your response.',
            "- If the task is a duplicate or already handled, close it: "
            'execute_action(action="close_task", params={"id": "ID"}) then '
            "include [WORK_DONE].",
            "- If the task cannot be done (missing info, wrong "
            "department, no access), close it with a note: "
            'execute_action(action="update_task", params={"task_id": "ID", '
            '"status": "done", "description": "Cannot execute: reason"}) '
            "then include [WORK_DONE].",
            "- Do NOT leave tasks open if you cannot make "
            "progress. Close or reassign them.",
            "",
        ]

        dropped = int(getattr(self, "_dropped_tag_steps", 0) or 0)
        if dropped:
            lines[0:0] = [
                f"CORRECTION - {dropped} of your previous step(s) in this session",
                "emitted [ACTION:...] tags. That syntax is DISABLED here, so those",
                "tags executed nothing and the steps did no work. Do not write tags.",
                "Call a tool directly, right now, before anything else.",
                "",
            ]
'''

HELPER_ANCHOR = '        return "blocker" in lower and "evidence" in lower\n\n    def _close_unfinished_work_session(\n'

EDITS = [
    ("helper", HELPER_ANCHOR, HELPER_NEW),
    ("reset", RESET_OLD, RESET_NEW),
    ("detector", DETECT_OLD, DETECT_NEW),
    ("prompt", PROMPT_OLD, PROMPT_NEW),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    # --- Gate 1: every anchor must match exactly once. -------------------
    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  anchor {name!r} matched {n} time(s), need exactly 1")
    if problems:
        print("REFUSING: anchors did not match uniquely; nothing written.")
        print("\n".join(problems))
        return 1

    # --- Gate 2: the dead instruction must be present pre-fix. ----------
    dead = "Use [ACTION:...] tags to take concrete actions"
    if text.count(dead) != 1:
        print(f"REFUSING: expected exactly 1 dead instruction, found {text.count(dead)}")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()

    # --- Backup ---------------------------------------------------------
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text
    for _name, old, replacement in EDITS:
        new = new.replace(old, replacement, 1)

    # --- Gate 3: post-conditions ----------------------------------------
    checks = [
        ("helper defined", "def _dropped_action_tag_count(" in new),
        ("detector wired", "_dropped_action_tag_count(reply, actions)" in new),
        ("marker emitted", "DROPPED-ACTION-TAGS" in new),
        ("reset present", "self._dropped_tag_steps = 0" in new),
        ("correction block", "lines[0:0] = [" in new),
        ("dead instruction gone", dead not in new),
        ("new instruction present", "Do NOT write [ACTION:...] tags" in new),
        ("work_done kept", "[WORK_DONE]" in new),
        ("structured fallback kept", "assistant_response" in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    after = hashlib.sha256(new.encode()).hexdigest()
    print(f"sha256 before: {before}")
    print(f"sha256 after:  {after}")
    print(f"backup:        {BACKUP}")
    print(f"bytes: {len(text)} -> {len(new)}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
