"""Does the work-mode model actually emit a tool call when forced?

The measured problem: work sessions burn their 5-step budget narrating ("Let me
examine ...") without calling a tool, and the session then fails. Tools ARE bound
(`assistant_structured_actions_enabled` is True, and `_build_tool_list` is called
with `tools=copilot_tools`), and `tool_choice` is passed straight through to the
provider payload (`copilot_client.py:800`), defaulting to `"auto"` -- which lets
the model decline.

This probe answers two questions with one cheap call each:
  1. with `auto`, does the work-mode path produce tool_calls?  (expected: no)
  2. with `required`, does it produce tool_calls, or does the provider reject the
     value?  (the answer decides whether forcing is available at all)

Read-only: it makes LLM calls and prints, and writes nothing.
"""

from __future__ import annotations

import sys

from app.config import settings
from app.assistant_chat import run_assistant_chat

PROMPT = (
    "WORK MODE - Step 1 of 5. Session: probe. Job type: task\n\n"
    "INSTRUCTIONS:\n"
    "- Take concrete actions by CALLING TOOLS DIRECTLY.\n"
    "- EVERY step must contain at least one tool call.\n\n"
    "TASK: record a memory that the tool-choice probe ran.\n"
)


def probe(choice: str | None) -> dict:
    try:
        res = run_assistant_chat(
            settings=settings,
            agent_id="dept_engineering",
            message=PROMPT,
            history=[],
            tier="fast",
            call_type="work_mode",
            tool_choice_override=choice,
        )
    except Exception as exc:  # noqa: BLE001
        return {"choice": choice, "error": f"{type(exc).__name__}: {str(exc)[:400]}"}

    reply = str(res.get("reply") or "")
    calls = res.get("tool_calls") or res.get("actions") or []
    return {
        "choice": choice,
        "ok": True,
        "model": res.get("model"),
        "tool_calls": len(calls) if isinstance(calls, list) else str(type(calls)),
        "reply_head": reply[:300].replace("\n", " "),
        "mentions_action_tag": "[ACTION:" in reply,
    }


if __name__ == "__main__":
    choices = sys.argv[1:] or ["auto", "required"]
    for c in choices:
        print(f"--- tool_choice={c!r} ---")
        for k, v in probe(c).items():
            print(f"    {k}: {v}")
