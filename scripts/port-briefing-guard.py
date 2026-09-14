"""Hand-port the briefing-envelope guard into the authority's live checkout.

Same gate discipline as port-work-mode-fix.py: every anchor must match EXACTLY
ONCE or the script refuses and writes nothing. Needed because deploy.sh cannot
run on the authority (the checkout is 87 commits diverged and its pull is
`--ff-only` under pipefail).
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/personal_assistant_context.py")
BACKUP = Path(".runtime/deploy-backups/handport-briefing.py.pre")

IMPORT_OLD = "import logging\nimport sqlite3\n"
IMPORT_NEW = "import json\nimport logging\nimport sqlite3\n"

GUARD_FN = '''

def is_model_action_envelope(text: str) -> bool:
    """True when `text` is a model action envelope rather than human prose.

    Found in production 2026-09-14. `build_llm_briefing` took the model's reply
    verbatim and used it as the owner-facing briefing when it was longer than 50
    characters. When the model answered with a *tool call* instead of prose, the
    reply was the structured envelope, and 41 of 102 owner briefings in
    `owner_message_queue` have a body that is exactly that JSON -- 20 evening of
    50 and 21 morning of 52, from 2026-07-06 through 2026-09-14.

        {"reply": "", "actions": [{"name": "list_tasks", "params": {"status": "open"}}]}

    A briefing must be prose. The envelope is a machine instruction that happens
    to be longer than 50 characters, so the length check could not catch it, and
    the failure is invisible until someone reads the queue.

    Deliberately conservative about what counts as prose: it rejects only text
    that is *entirely* a JSON object, or that clearly carries an `actions` array.
    A briefing that merely mentions a brace is left alone.
    """
    raw = str(text or "").strip()
    if not raw:
        return False
    if raw.startswith("{") and raw.endswith("}"):
        try:
            payload = json.loads(raw)
        except Exception:  # noqa: BLE001
            # A brace-wrapped blob that will not parse is still not a briefing.
            return True
        if isinstance(payload, dict):
            return True
    lowered = raw.lower()
    if '"actions"' in lowered and '"reply"' in lowered and raw.startswith("{"):
        return True
    return False
'''

LOG_OLD = "log = logging.getLogger(__name__)\n"
LOG_NEW = "log = logging.getLogger(__name__)\n" + GUARD_FN

USE_OLD = '''        synthesized = ""
        if isinstance(result, dict):
            if result.get("ok"):
                synthesized = str(result.get("reply") or "").strip()
        else:
            synthesized = str(result or "").strip()
        if synthesized and len(synthesized) > 50:
            return synthesized
'''

USE_NEW = '''        synthesized = ""
        if isinstance(result, dict):
            if result.get("ok"):
                synthesized = str(result.get("reply") or "").strip()
        else:
            synthesized = str(result or "").strip()
        if is_model_action_envelope(synthesized):
            # The model chose to call a tool instead of writing the briefing. The
            # envelope is a machine instruction, not something to send a person.
            log.warning(
                "LLM briefing synthesis returned a model action envelope, not prose "
                "(%d chars) - using the deterministic briefing instead",
                len(synthesized),
            )
            return raw
        if synthesized and len(synthesized) > 50:
            return synthesized
'''

EDITS = [
    ("import-json", IMPORT_OLD, IMPORT_NEW),
    ("guard-function", LOG_OLD, LOG_NEW),
    ("guarded-branch", USE_OLD, USE_NEW),
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
        ("json imported", "import json" in new),
        ("guard defined", "def is_model_action_envelope(" in new),
        ("guard called", "if is_model_action_envelope(synthesized):" in new),
        ("length guard kept", "if synthesized and len(synthesized) > 50:" in new),
        ("fallback kept", "return raw" in new),
        ("old blind branch gone", USE_OLD not in new),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 before: {before}")
    print(f"sha256 after:  {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"bytes: {len(text)} -> {len(new)}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
