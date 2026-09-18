"""End-to-end check that the DEPLOYED work-mode prompt produces real action.

The earlier probe used a hand-written prompt. This one uses the real
`AutopilotController._build_work_prompt`, so it tests exactly what is running on
the authority, and it reports whether `parse_actions()` -- the function the work
loop actually calls -- extracts executable actions from the reply.

This is the test that matters: the earlier one proved the model *can* act, this
one proves the deployed prompt *gets* it to, through the real parse path.

Read-only: LLM calls and prints; writes nothing.
"""

from __future__ import annotations

import json
from types import SimpleNamespace

from app.config import settings
from app.assistant_chat import run_assistant_chat
from app.autopilot import AutopilotController
from app.chat_actions import parse_actions

# A real, small, achievable task shape -- the kind the goal generator produces.
SESSION = {
    "title": "Task #24956: tighten the goal quality gate",
    "total_steps": 5,
    "output_log": "",
    "steps_completed": 0,
}
CONTEXT = {
    "job_type": "task",
    "payload": {"task_id": 24956},
    "target_agent_id": "dept_engineering",
    "job_id": None,
}


def stub_self() -> SimpleNamespace:
    return SimpleNamespace(
        _agent_id="dept_engineering",
        _db_url=settings.database_url,
        _dropped_tag_steps=0,
        _settings=settings,
    )


def main() -> int:
    prompt = AutopilotController._build_work_prompt(
        stub_self(), SESSION, CONTEXT, "", 1
    )
    print("=== prompt guards ===")
    print("  contains dead instruction :", "Use [ACTION:...] tags to take concrete actions" in prompt)
    print("  contains the tag warning  :", "Do NOT write [ACTION:...] tags" in prompt)
    print("  requires a tool call      :", "EVERY step must contain at least one tool call" in prompt)
    print("  prompt bytes              :", len(prompt))

    res = run_assistant_chat(
        settings=settings,
        agent_id="dept_engineering",
        message=prompt,
        history=[],
        tier="fast",
        call_type="work_mode",
    )
    reply = str(res.get("reply") or "")
    cleaned, actions = parse_actions(reply)

    print("=== result ===")
    print("  model            :", res.get("model"))
    print("  reply bytes      :", len(reply))
    print("  ACTIONS PARSED   :", len(actions))
    if actions:
        for a in actions[:3]:
            print("    -", a.get("_action") or a.get("name"),
                  json.dumps({k: v for k, v in a.items() if k not in ("_action",)}, default=str)[:160])
    else:
        print("    reply head     :", reply[:400].replace("\n", " "))
    print("  dead tags in reply:", reply.count("[ACTION:"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
