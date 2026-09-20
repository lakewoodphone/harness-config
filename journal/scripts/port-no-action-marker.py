"""Hand-port the no-action observability marker into the authority's autopilot.py.

Gated: the anchor must match EXACTLY ONCE or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-no-action-marker.py.pre")

OLD = '''                if actions:
                    accumulated_output += (
                        f"[ACTIONS: {len(actions)} "
                        f"({', '.join(str(a.get('_action') or a.get('name') or '?') for a in actions[:4])})]\\n"
                    )
'''

NEW = '''                if actions:
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
        ("no-action marker", "[NO-ACTION: " in new),
        ("envelope recorded", "envelope=" in new),
        ("tags counted", "tags={_raw.count" in new),
        ("actions marker kept", "[ACTIONS: " in new),
        ("guard still requires no actions", "and not actions" in new),
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
