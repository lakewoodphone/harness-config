"""Port the evolution-health fix into the authority's live autopilot.py.

Gated: both anchors must match exactly once or nothing is written.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-evo-health.py.pre")

HELPER = '''    @staticmethod
    def _evolution_health_from_result(result: dict[str, Any]) -> tuple[bool, str]:
        """Health flag and detail for the evolution subsystem, from its own result.

        _record_subsystem("evolution", success=True) used to be called with NO detail
        whatever the cycle returned, so the subsystem reported 611 successes, zero
        failures and an empty last_detail while applying nothing for ten weeks
        (measured 2026-09-14; the apply path is off by configuration, so nothing
        applying is expected -- but a health metric that cannot distinguish "worked"
        from "ran" is the completion lie one layer up, and it is why nobody noticed).

        rolled_back counts as a failure on purpose: the cycle applied a change and the
        error-spike guard reverted it, which is a real problem rather than a no-op.
        """
        payload = result if isinstance(result, dict) else {}
        status = str(payload.get("status") or "unknown")
        applied = bool(payload.get("applied"))
        failed = status in {"error", "rolled_back"}
        detail = f"status={status} applied={'yes' if applied else 'no'}"
        reason = payload.get("reason")
        if reason:
            detail += f" reason={str(reason)[:140]}"
        elif payload.get("rollback_failed"):
            detail += f" rollback_failed={str(payload['rollback_failed'])[:100]}"
        return (not failed), detail

'''

ANCHOR = "    def _record_subsystem(\n"

CALL_OLD = '''                    proactive_actions.append(f"Evolution: {evo_status}")
                    self._record_subsystem(
                        "evolution",
                        success=True,
                    )
'''

CALL_NEW = '''                    proactive_actions.append(f"Evolution: {evo_status}")
                    _evo_ok, _evo_detail = self._evolution_health_from_result(
                        evolution_result
                    )
                    self._record_subsystem(
                        "evolution",
                        success=_evo_ok,
                        detail=_evo_detail,
                    )
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if text.count(ANCHOR) != 1:
        print(f"REFUSING: helper anchor matched {text.count(ANCHOR)} times, need 1")
        return 1
    if text.count(CALL_OLD) != 1:
        print(f"REFUSING: call anchor matched {text.count(CALL_OLD)} times, need 1")
        return 1

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    new = text.replace(ANCHOR, HELPER + ANCHOR, 1)
    new = new.replace(CALL_OLD, CALL_NEW, 1)

    checks = [
        ("helper defined", "def _evolution_health_from_result(" in new),
        ("call site uses it", "success=_evo_ok" in new),
        ("no hard-coded success for evolution", CALL_OLD not in new),
        ("record_subsystem intact", "def _record_subsystem(" in new),
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
