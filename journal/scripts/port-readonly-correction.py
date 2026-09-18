"""Port the read-only reconnaissance correction into the live tree.

Gated: every anchor must match exactly once.

Measured: session 75341 ran five steps of repo_list_dir/repo_search, said in step 5
that "the previous steps only explored the repo without producing actual test code",
and then searched again. Every recent session failed at 5/5 while executing actions;
the actions were reconnaissance.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-readonly.py.pre")

HELPER = '''    # Actions that only READ. A step whose actions are all in this set has learned
    # something and changed nothing.
    _READ_ONLY_ACTION_PREFIXES = (
        "list_", "get_", "read_", "search_", "show_", "view_", "check_", "find_",
        "query_",
    )
    _READ_ONLY_ACTIONS = frozenset({
        "system_health", "task_hygiene", "repo_list_dir", "repo_read_file",
        "repo_search", "github_read_file", "github_list_issues", "web_search",
        "fetch_url", "get_current_datetime", "list_dynamic_tools",
        "read_call_transcript",
    })

    @classmethod
    def _actions_are_read_only(cls, actions: list[Any]) -> bool:
        """True when every action in a step only looked at something.

        Measured on the authority 2026-09-14, session 75341: all five steps executed
        repo_list_dir and repo_search, step 5 said "the previous steps only explored
        the repo without producing actual test code" -- and then searched again. Every
        recent work session failed at 5/5 while executing actions; the actions were
        reconnaissance, and five read-only steps cannot complete a task.

        False for an empty action list, so "no action" is never counted as "read-only"
        and the two corrections stay independent.
        """
        if not actions:
            return False
        names = [
            str(a.get("_action") or a.get("name") or "").strip().lower()
            for a in actions
            if isinstance(a, dict)
        ]
        names = [n for n in names if n]
        if not names:
            return False
        return all(
            n in cls._READ_ONLY_ACTIONS or n.startswith(cls._READ_ONLY_ACTION_PREFIXES)
            for n in names
        )

'''

ANCHOR1 = "    def _task_is_closed(self, task_id: Any | None) -> bool:\n"
ANCHOR2 = "        self._dropped_tag_steps = 0\n"
ANCHOR3 = '                accumulated_output += step_marker + "\\n"\n'
ANCHOR4 = '        dropped = int(getattr(self, "_dropped_tag_steps", 0) or 0)\n'

NEW2 = '''        self._dropped_tag_steps = 0
        # And how many consecutive steps did reconnaissance only.
        self._readonly_steps = 0
'''

NEW3 = '''                if actions:
                    if self._actions_are_read_only(actions):
                        self._readonly_steps = (
                            int(getattr(self, "_readonly_steps", 0) or 0) + 1
                        )
                    else:
                        self._readonly_steps = 0
                accumulated_output += step_marker + "\\n"
'''

NEW4 = '''        readonly = int(getattr(self, "_readonly_steps", 0) or 0)
        if readonly >= 2:
            lines[0:0] = [
                f"STOP SEARCHING - {readonly} consecutive steps only READ things.",
                "You have learned enough to start. Take a MUTATING action in this step:",
                "write or edit a file, create the artefact, update or close the task.",
                "If you genuinely cannot act, say why and include [WORK_DONE].",
                "",
            ]

        dropped = int(getattr(self, "_dropped_tag_steps", 0) or 0)
'''

EDITS = [
    ("helper", ANCHOR1, HELPER + ANCHOR1),
    ("reset", ANCHOR2, NEW2),
    ("counter", ANCHOR3, NEW3),
    ("correction", ANCHOR4, NEW4),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    problems = []
    for name, old, _new in EDITS:
        n = text.count(old)
        if n != 1:
            problems.append(f"  {name}: anchor matched {n} time(s), need 1")
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
        ("helper defined", "def _actions_are_read_only(" in new),
        ("counter reset", "self._readonly_steps = 0" in new),
        ("counter updated", "_actions_are_read_only(actions)" in new),
        ("correction present", "STOP SEARCHING" in new),
        ("tag correction kept", '"_dropped_tag_steps"' in new),
        ("tag marker kept", "[ACTIONS: " in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
