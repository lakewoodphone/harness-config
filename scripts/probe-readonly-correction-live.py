"""Did the STOP SEARCHING correction actually reach the prompt?

Session 75343 ran after the deploy and stayed read-only for all five steps, so the
correction did not change behaviour. Before concluding anything about the model, check
the wiring: build the real work prompt with `_readonly_steps` set to 2 and see whether
the correction text is in it.

If it IS present, the model ignored a clear instruction and the fix is not a prompt fix.
If it is NOT present, the wiring is wrong and none of the session's behaviour says
anything about the model.
"""

from __future__ import annotations

import sys
from types import SimpleNamespace

sys.path.insert(0, ".")

from app.autopilot import AutopilotController as Autopilot  # noqa: E402
from app.config import settings  # noqa: E402

SESSION = {"title": "Audit agent memory usage and optimize retrieval prompts",
           "total_steps": 5, "output_log": "", "steps_completed": 0}
CONTEXT = {"job_type": "task", "payload": {"task_id": 24992}}


def stub(readonly: int):
    return SimpleNamespace(
        _agent_id="dept_engineering",
        _db_url=settings.database_url,
        _dropped_tag_steps=0,
        _readonly_steps=readonly,
        _settings=settings,
    )


def main() -> int:
    for count in (0, 1, 2, 3):
        prompt = Autopilot._build_work_prompt(stub(count), SESSION, CONTEXT, "", 3)
        present = "STOP SEARCHING" in prompt
        head = prompt.splitlines()[0][:80] if prompt else ""
        print(f"  _readonly_steps={count}: correction present={present}  first line={head!r}")
    print()
    p2 = Autopilot._build_work_prompt(stub(2), SESSION, CONTEXT, "", 3)
    if "STOP SEARCHING" in p2:
        i = p2.find("STOP SEARCHING")
        print("  the correction as built:")
        for line in p2[i: i + 340].splitlines():
            print("    |", line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
