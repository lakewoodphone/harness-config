#!/usr/bin/env python3
"""Feed tool results back to the model, so a work session can accumulate facts.

THE DEFECT: in the work loop, `execute_actions()` results were pushed only into
`proactive_actions` -- the tick's notes. `_build_work_prompt()` is built from
`accumulated_output`, which carried the model's prose and the NAMES of the actions
it called, never their RESULTS. So a session asked a question, never saw the
answer, asked it again next step, and died at the step budget having learned
nothing.

Measured on secratary 2026-09-14, work_sessions since 2026-09-12: every failed
session sat at 5/5 steps and progress_pct 99, and its log showed only
reconnaissance -- [ACTIONS: 1 (qb_status)], [ACTIONS: 2 (ha_states, list_tasks)] --
while tasks #25095 and #25103 were re-claimed three and four times respectively.
The prompt already said STOP SEARCHING after two read-only steps and was ignored,
which makes sense: stopping would mean acting while blind.

This is why the loop cannot succeed no matter how large the step budget is, and
why the earlier fixes (making action names visible in the log, adding the
reconnaissance nudge) changed the symptom's visibility without changing the
outcome.
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

# ── 1. the renderer, next to the other action helpers ──────────────────────
ANCHOR_HELPER = '''    @classmethod
    def _actions_are_read_only(cls, actions: list[Any]) -> bool:'''

NEW_HELPER = '''    # A single tool's payload is bounded so one chatty tool cannot poison the
    # context the next step is built from (P7); the whole block is bounded too,
    # because the prompt is rebuilt from accumulated_output on every step.
    _TOOL_RESULT_CHARS = 900
    _TOOL_RESULTS_CHARS = 4000

    @classmethod
    def _render_tool_results(cls, results: list[Any]) -> str:
        """Render executed action results for the NEXT step to read.

        `accumulated_output` is the only thing `_build_work_prompt` is built from.
        Before this existed, a session's own tool output reached the tick's notes
        and nothing else, so the model re-queried the same state every step and
        could not accumulate a single fact. Returns "" when there is nothing to
        say, so a step with no actions leaves the log unchanged.
        """
        if not results:
            return ""
        import json

        blocks: list[str] = []
        for r in results:
            if r is None:
                continue
            name = str(getattr(r, "action", "?") or "?")
            ok = bool(getattr(r, "success", False))
            detail = " ".join(str(getattr(r, "detail", "") or "").split())
            head = f"- {name}: {'ok' if ok else 'FAILED'}"
            if detail:
                head += f" -- {detail[:cls._TOOL_RESULT_CHARS]}"
            data = getattr(r, "data", None)
            if data:
                try:
                    payload = json.dumps(data, default=str, ensure_ascii=False)
                except Exception:
                    payload = str(data)
                payload = " ".join(payload.split())
                if payload and payload not in ("{}", "null"):
                    head += f" | data: {payload[:cls._TOOL_RESULT_CHARS]}"
            blocks.append(head)
        if not blocks:
            return ""
        body = "\\n".join(blocks)[:cls._TOOL_RESULTS_CHARS]
        return (
            "[TOOL RESULTS - what your last actions actually returned. "
            "Use these; do not ask for the same thing again.]\\n" + body
        )

    @classmethod
    def _actions_are_read_only(cls, actions: list[Any]) -> bool:'''

# ── 2. wire it into the work loop ──────────────────────────────────────────
OLD_CALL = '''                if actions:
                    results = execute_actions(
                        actions,
                        settings=self._settings,
                        agent_id=run_agent_id,
                    )
                    for r in results:
                        status = "OK" if r.success else r.detail
                        proactive_actions.append(f"Work action {r.action}: {status}")
'''

NEW_CALL = '''                if actions:
                    results = execute_actions(
                        actions,
                        settings=self._settings,
                        agent_id=run_agent_id,
                    )
                    for r in results:
                        status = "OK" if r.success else r.detail
                        proactive_actions.append(f"Work action {r.action}: {status}")
                    # These results must reach the model, not just the tick's
                    # notes. `accumulated_output` is what the next step's prompt is
                    # built from; without this the session re-asked the same
                    # question every step and died at the step budget having
                    # learned nothing (see _render_tool_results).
                    rendered = self._render_tool_results(results)
                    if rendered:
                        accumulated_output += f"\\n{rendered}\\n"
'''

TEST = '''"""The work loop must show the model what its own tools returned.

Measured on secratary 2026-09-14: every failed work session ran 5/5 steps of pure
reconnaissance and progress_pct 99, re-claiming the same task three and four times.
Action results were written to the tick's notes only, while the next step's prompt
was rebuilt from accumulated_output, which held the model's prose and the names of
the actions it called -- never their results.
"""

from app.autopilot import Autopilot
from app.chat_action_parsing import ActionResult


def _autopilot_stub() -> Autopilot:
    """An instance with only the attributes the prompt builder reads."""
    ap = Autopilot.__new__(Autopilot)
    ap._readonly_steps = 0
    ap._dropped_tag_steps = 0
    return ap


def test_results_are_rendered_with_detail_and_data():
    ap = _autopilot_stub()
    rendered = ap._render_tool_results([
        ActionResult("ha_states", True, "3 sensors unavailable", {"count": 3}),
        ActionResult("list_tasks", False, "permission denied", {}),
    ])
    assert "ha_states" in rendered and "3 sensors unavailable" in rendered
    assert '"count": 3' in rendered
    assert "list_tasks" in rendered and "FAILED" in rendered


def test_nothing_to_say_renders_nothing():
    ap = _autopilot_stub()
    assert ap._render_tool_results([]) == ""
    assert ap._render_tool_results([None]) == ""


def test_a_chatty_tool_cannot_flood_the_context():
    ap = _autopilot_stub()
    rendered = ap._render_tool_results([
        ActionResult("huge", True, "x" * 50_000, {"blob": "y" * 50_000}),
    ])
    assert len(rendered) < Autopilot._TOOL_RESULTS_CHARS + 200, len(rendered)


def test_the_next_step_prompt_contains_the_previous_tool_result():
    """The end-to-end property: a fact learned in step 1 is visible in step 2."""
    ap = _autopilot_stub()
    session = {"id": 1, "title": "HA alert: door contact sensors unavailable", "total_steps": 5}
    context = {"payload": {}, "job_type": "general"}

    rendered = ap._render_tool_results([
        ActionResult("ha_states", True, "binary_sensor.garage_door is unavailable", {}),
    ])
    first_step_log = f"Step 1: checking the sensors\\n{rendered}\\n"
    prompt = ap._build_work_prompt(session, context, first_step_log, 2)

    assert "binary_sensor.garage_door is unavailable" in prompt, prompt[:600]
'''


def main() -> int:
    src_path = pathlib.Path("app/autopilot.py")
    src = src_path.read_text(encoding="utf-8")

    assert src.count(ANCHOR_HELPER) == 1, f"helper anchor: {src.count(ANCHOR_HELPER)}"
    assert src.count(OLD_CALL) == 1, f"call site: {src.count(OLD_CALL)}"

    backup = BACKUPS / f"autopilot.py.{STAMP}.bak"
    if not backup.exists():
        shutil.copy("app/autopilot.py", backup)

    src = src.replace(ANCHOR_HELPER, NEW_HELPER)
    src = src.replace(OLD_CALL, NEW_CALL)
    src_path.write_text(src, encoding="utf-8")
    print("patched app/autopilot.py")

    pathlib.Path("tests/test_tool_results_reach_the_prompt.py").write_text(
        TEST, encoding="utf-8"
    )
    print("wrote tests/test_tool_results_reach_the_prompt.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
