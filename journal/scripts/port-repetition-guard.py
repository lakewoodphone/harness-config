"""Hand-port the repetition-guard fix into the authority's live autopilot.py.

Gated like the other ports: the anchor must match EXACTLY ONCE or nothing is
written.

Why the guard matters: session 75335 on the authority was closed as
`stalled_repeating_output` after three steps that repeated the phrase "let me
identify which task is stale by listing tasks" -- the phrasing of an agent CALLING
`list_tasks`. The guard saw only prose, so it could fail a session for working.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-repetition-guard.py.pre")

OLD = '''                accumulated_output += f"\\n--- Step {current_step} ---\\n" f"{cleaned}\\n"

                # \u2500\u2500 Repetition guard: detect identical/near-identical output \u2500\u2500
                if hasattr(self, "_last_work_output"):
                    if (
                        cleaned
                        and self._last_work_output
                        and len(cleaned) > 50
                        and _text_similarity(cleaned, self._last_work_output) > 0.85
                    ):
'''

NEW = '''                accumulated_output += f"\\n--- Step {current_step} ---\\n" f"{cleaned}\\n"

                # -- Actions taken this step, made visible ------------------
                # `execute_actions` results were reported only through
                # `proactive_actions`, which is the tick's notes and never the
                # session's own `output_log`. So a session's log could not say
                # whether any work happened, and an audit of 386 failed sessions
                # wrongly concluded none had executed an action.
                if actions:
                    accumulated_output += (
                        f"[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]\\n"
                    )

                # -- Repetition guard: detect identical/near-identical output --
                # `and not actions` is the 2026-09-14 fix. The guard compared only
                # the model's PROSE and knew nothing about whether the step had
                # executed anything, so a session that was genuinely working got
                # closed as `stalled_repeating_output` for sounding repetitive.
                # Session 75335 is the case: three steps repeating "let me identify
                # which task is stale by listing tasks" -- the phrasing of an agent
                # calling `list_tasks` -- were counted as a stall and it failed.
                # A step that executed an action did work; its commentary is style.
                if hasattr(self, "_last_work_output"):
                    if (
                        cleaned
                        and self._last_work_output
                        and len(cleaned) > 50
                        and _text_similarity(cleaned, self._last_work_output) > 0.85
                        and not actions
                    ):
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    n = text.count(OLD)
    if n != 1:
        print(f"REFUSING: anchor matched {n} time(s), need exactly 1; nothing written.")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text.replace(OLD, NEW, 1)

    checks = [
        ("guard requires no actions", "and not actions" in new),
        ("actions marker emitted", "[ACTIONS: " in new),
        ("similarity check kept", "_text_similarity(cleaned, self._last_work_output) > 0.85" in new),
        ("stall path kept", "_repeat_count" in new),
        ("old condition gone", "> 0.85\n                    ):" not in new),
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
