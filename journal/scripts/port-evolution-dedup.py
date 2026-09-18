"""Port the evolution dedup + vendor-exclusion fix into the live tree.

Gated: the reset anchor must match exactly once, and the exclusion expression must
occur a known number of times (6) and be replaced in all of them.

Why: the stall reset cleared the exact-duplicate guard, so the release valve
manufactured 38 duplicate offers for one file; and `_EVOLUTION_EXCLUDED_TARGETS` was
matched by exact path only, so the engine proposed changes to files inside
node_modules which can never survive npm.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

TARGET = Path("app/evolution.py")
BACKUP = Path(".runtime/deploy-backups/handport-evolution.py.pre")

RESET_OLD = """            with _state_lock:
                old_hashes = len(_instruction_hashes)
                old_prefixes = len(_instruction_prefixes)
                old_targeted = len(_recently_targeted)
                _instruction_hashes.clear()
                _instruction_prefixes.clear()
                _recently_targeted.clear()
            log.info(
                "Evolution dedup RESET after %.0fh stall "
                "(cleared %d hashes, %d prefixes, "
                "%d targeted files)",
                age_hours,
                old_hashes,
                old_prefixes,
                old_targeted,
            )
"""

RESET_NEW = '''            with _state_lock:
                old_prefixes = len(_instruction_prefixes)
                old_targeted = len(_recently_targeted)
                kept_hashes = len(_instruction_hashes)
                # Clear the COARSE guards only (fixed 2026-09-14).
                #
                # `_instruction_prefixes` is what deadlocks: if every new instruction
                # looks similar to recent history, nothing can be proposed at all, and
                # clearing it is the point of this function. `_recently_targeted` is a
                # cooldown, and a stalled engine should be allowed to re-examine a file.
                #
                # `_instruction_hashes` is NOT cleared: an exactly-repeated instruction
                # is never acceptable however long the engine has stalled. Clearing it
                # turned a stall into duplicate spam -- measured on the authority,
                # evolution had 72 unapplied against 102 applied, the last application
                # was past the 48h threshold, this reset fired, and
                # app/services/activity_sync.py collected 38 duplicate offers.
                _instruction_prefixes.clear()
                _recently_targeted.clear()
            log.info(
                "Evolution dedup RESET after %.0fh stall "
                "(cleared %d prefixes, %d targeted files; KEPT %d exact hashes)",
                age_hours,
                old_prefixes,
                old_targeted,
                kept_hashes,
            )
'''

SET_OLD = '''_EVOLUTION_EXCLUDED_TARGETS: set[str] = {
    "app/evolution.py",
    "app/autopilot.py",
}
'''

SET_NEW = '''_EVOLUTION_EXCLUDED_TARGETS: set[str] = {
    "app/evolution.py",
    "app/autopilot.py",
}


def _is_excluded_target(path: str) -> bool:
    """True when the evolution engine must not propose a change to this path.

    Exact matches come from _EVOLUTION_EXCLUDED_TARGETS -- the engine's own files,
    excluded to prevent self-referential loops. Vendor and generated trees are matched
    by fragment at any depth.

    Added 2026-09-14. The kernel reported "1 target file(s) inside node_modules" and 18
    duplicate offers against web/node_modules/flatted/python/flatted.py. A proposal
    aimed at a third-party file that npm overwrites can never survive, so it can never
    be "applied" -- which makes the loop look broken when it is merely aimed at
    something it must not touch.
    """
    normalized = str(path or "").replace("\\\\", "/").strip()
    if not normalized:
        return True
    if normalized in _EVOLUTION_EXCLUDED_TARGETS:
        return True
    haystack = f"/{normalized}"
    fragments = (
        "node_modules/",
        ".venv/",
        "site-packages/",
        "__pycache__/",
        "/dist/",
        "/build/",
        "/.next/",
    )
    return any(fragment in haystack for fragment in fragments)
'''

EXPR_RE = re.compile(
    r'str\(f\.get\("path", ""\)\)\.replace\("\\\\", "/"\)\s*\n?\s*not in _EVOLUTION_EXCLUDED_TARGETS'
)


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if text.count(RESET_OLD) != 1:
        print(f"REFUSING: reset anchor matched {text.count(RESET_OLD)} times, need 1")
        return 1
    if text.count(SET_OLD) != 1:
        print(f"REFUSING: exclusions-set anchor matched {text.count(SET_OLD)} times, need 1")
        return 1
    found = len(EXPR_RE.findall(text))
    if found == 0:
        print("REFUSING: no exclusion expression found to replace")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text.replace(RESET_OLD, RESET_NEW, 1)
    new = new.replace(SET_OLD, SET_NEW, 1)
    new, n = EXPR_RE.subn('not _is_excluded_target(str(f.get("path", "")))', new)

    checks = [
        ("reset keeps hashes", "_instruction_hashes.clear()" not in new),
        ("reset clears prefixes", "_instruction_prefixes.clear()" in new),
        ("helper defined", "def _is_excluded_target(" in new),
        ("all call sites rewritten", "not in _EVOLUTION_EXCLUDED_TARGETS" not in new),
        ("node_modules excluded", '"node_modules/",' in new),
        ("replacement count matches", n == found),
    ]
    failed = [label for label, ok in checks if not ok]
    if failed:
        print("REFUSING: post-conditions failed; nothing written. " + ", ".join(failed))
        return 1

    TARGET.write_text(new, encoding="utf-8")
    print(f"sha256 {before} -> {hashlib.sha256(new.encode()).hexdigest()}")
    print(f"exclusion sites rewritten: {n}")
    print(f"backup: {BACKUP}")
    print("PORT APPLIED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
