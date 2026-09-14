"""Can the model mutate when the read-only tools are absent?

The experiment that discriminates the two structural fixes named in L238. A prompt
correction telling the model to stop searching was provably present and provably
ignored (session 75343, steps 3-5). The open question is whether the model *cannot*
mutate on this task shape, or merely will not.

Method: run the real work prompt for the same task shape that failed (session 75343's
"audit agent memory usage"), with the tiered tool classifier monkeypatched to offer
ONLY mutating actions. If the model calls one, enforcement works and the fix is to
remove the choice. If it still narrates or reaches for a read-only tool that is not
bound, the problem is deeper than tool availability.

Read-only in intent: one LLM call, prints what came back, writes nothing.
"""

from __future__ import annotations

import sys

sys.path.insert(0, ".")

MUTATING_ONLY = [
    "save_memory",
    "update_task",
    "close_task",
    "create_task",
    "code_edit",
    "repo_run_command",
    "github_write_file",
    "send_directive",
]

# The exact task shape from session 75343, which stayed read-only for five steps.
PROMPT = (
    "WORK MODE - Step 3 of 5\n"
    "Session: Audit agent memory usage and optimize retrieval prompts\n"
    "Job type: task\n\n"
    "INSTRUCTIONS:\n"
    "- Take concrete actions by CALLING TOOLS DIRECTLY (native tool calling).\n"
    "- Do NOT write [ACTION:...] tags.\n"
    "- EVERY step must contain at least one tool call.\n\n"
    "STOP SEARCHING - 2 consecutive steps only READ things.\n"
    "You have learned enough to start. Take a MUTATING action in this step:\n"
    "write or edit a file, create the artefact, update or close the task.\n"
    "If you genuinely cannot act, say why and include [WORK_DONE].\n\n"
    "Previous work output:\n"
    "Step 1: Let me examine the current memory system and retrieval setup.\n"
    "Step 2: Let me continue the audit by examining the memory system.\n"
)


def main() -> int:
    import app.tool_classifier as tc
    from app.assistant_chat import run_assistant_chat
    from app.chat_actions import parse_actions
    from app.config import settings

    offered: list[str] = []

    def _only_mutating(_message: str):
        offered.append("called")
        return list(MUTATING_ONLY)

    tc.select_tools_for_message = _only_mutating  # type: ignore[assignment]

    print("offered tool set:", MUTATING_ONLY)
    try:
        res = run_assistant_chat(
            settings=settings,
            agent_id="dept_engineering",
            message=PROMPT,
            history=[],
            tier="fast",
            call_type="work_mode",
        )
    except Exception as exc:  # noqa: BLE001
        print(f"raised {type(exc).__name__}: {exc}")
        return 0

    reply = str(res.get("reply") or "")
    _cleaned, actions = parse_actions(reply)
    names = [str(a.get("_action") or a.get("name") or "?") for a in actions]
    print(f"classifier consulted: {bool(offered)}")
    print(f"model: {res.get('model')}")
    print(f"actions returned: {names}")
    mutating = [
        n for n in names
        if n in MUTATING_ONLY or not n.startswith(
            ("list_", "get_", "read_", "search_", "show_", "view_", "check_", "find_", "query_")
        )
    ]
    print(f"mutating among them: {mutating}")
    print(f"VERDICT: {'CAN mutate when read-only tools are absent' if mutating else 'did NOT mutate even with only mutating tools offered'}")
    if not actions:
        print("reply head:", reply[:400].replace("\n", " "))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
