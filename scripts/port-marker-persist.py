"""Fix my own instrumentation: the marker must be PERSISTED, not only accumulated.

`accumulated_output` is an in-memory accumulator that feeds the next prompt; it is
never written to the database. The persisted field is the `output_append=` argument
to `update_work_session`. The previous port wrote the marker only to
`accumulated_output`, so after deploying it, zero rows carried it -- and that is
how the mistake was found: by reading where `Step N: <prose>` actually comes from.

Gated: every anchor must match EXACTLY ONCE or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-marker-persist.py.pre")

BLOCK_OLD = '''                if actions:
                    accumulated_output += (
                        f"[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]\\n"
                    )
                else:
                    # A step that produced nothing is the interesting case, and the
                    # log used to be silent about it -- which is why an audit of 386
                    # failed sessions could not tell "the model never called a tool"
                    # from "it called one and the parser dropped it". Record the
                    # shape of what came back, not just its prose.
                    _raw = str(reply or "")
                    _head = " ".join(str(cleaned or "").split())[:160]
                    accumulated_output += (
                        f"[NO-ACTION: reply={len(_raw)}c cleaned={len(str(cleaned or ''))}c "
                        f"envelope={'yes' if _raw.lstrip().startswith('{') else 'no'} "
                        f"tags={_raw.count('[ACTION:')} head={_head}]\\n"
                    )
'''

BLOCK_NEW = '''                step_marker = ""
                if actions:
                    step_marker = (
                        f"\\n[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]"
                    )
                else:
                    # A step that produced nothing is the interesting case, and the
                    # log used to be silent about it -- which is why an audit of 386
                    # failed sessions could not tell "the model never called a tool"
                    # from "it called one and the parser dropped it".
                    _raw = str(reply or "")
                    _head = " ".join(str(cleaned or "").split())[:160]
                    step_marker = (
                        f"\\n[NO-ACTION: reply={len(_raw)}c cleaned={len(str(cleaned or ''))}c "
                        f"envelope={'yes' if _raw.lstrip().startswith('{') else 'no'} "
                        f"tags={_raw.count('[ACTION:')} head={_head}]"
                    )
                accumulated_output += step_marker + "\\n"
'''

PERSIST_OLD = '                    output_append=f"Step {current_step}: {cleaned[:500]}",\n'
PERSIST_NEW = '                    output_append=f"Step {current_step}: {cleaned[:500]}{step_marker}",\n'

EDITS = [
    ("marker-to-variable", BLOCK_OLD, BLOCK_NEW),
    ("persist-the-marker", PERSIST_OLD, PERSIST_NEW),
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
        ("marker is a variable", "step_marker = \"\"" in new),
        ("accumulated gets it", "accumulated_output += step_marker" in new),
        ("output_append gets it", "{cleaned[:500]}{step_marker}" in new),
        ("actions branch kept", "[ACTIONS: " in new),
        ("no-action branch kept", "[NO-ACTION: " in new),
        ("guard untouched", "and not actions" in new),
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
