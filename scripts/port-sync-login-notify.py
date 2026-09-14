"""Port the "tell the owner when a sync needs a login" fix into the live tree.

Gated: the helper anchor must match EXACTLY ONCE and each of the five log lines must
be found exactly once; otherwise nothing is written.

The five lines are matched by their distinctive prefix rather than by the full text,
because the em dash in them is easy to mismatch; the whole line is then replaced.
"""

from __future__ import annotations

import hashlib
import re
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-sync-login.py.pre")

ANCHOR = """        except Exception as exc:  # noqa: BLE001
            logger.debug("sync breaker nudge failed (%s): %s", name, exc)
"""

HELPER = '''
    def _notify_owner_sync_needs_login(self, name: str, detail: str = "") -> None:
        """Tell the owner that a sync needs an interactive login.

        Five syncs (BoA, Chase, Amex, Amazon, eBay) each had a needs_mfa branch that
        did nothing but log "will surface in next owner check-in" and enqueued
        nothing, so the promise was false and an MFA wall stayed invisible. Measured
        2026-09-14: amazon_sync and ebay_sync sat at 42 consecutive failures each and
        the reason -- "Amazon login requires MFA", "Authentication failed" -- existed
        only in a log line nobody read.

        Enqueued with status="held" deliberately. A held row is counted by the
        attention-debt check and rendered by the harness badge, which is the channel
        the owner chose; and it cannot become an outbound SMS without a deliberate
        change, which matters because the SMS kill switch is his decision and this
        code must not manufacture sendable messages on its own. The queue dedups it,
        so a sync that keeps needing login becomes one row with a repeat count.
        """
        try:
            from app.database import enqueue_owner_message

            body = (
                f"{name} sync needs you: it cannot complete without an interactive "
                f"browser verification (MFA). {detail or ''}"
            ).strip()
            enqueue_owner_message(
                self._settings.database_url,
                body=body,
                reason=f"sync_needs_login:{name}",
                urgency="high",
                status="held",
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("sync login nudge failed (%s): %s", name, exc)

'''

SYNCS = [
    ("BoA", "boa_sync"),
    ("Chase", "chase_sync"),
    ("Amex", "amex_sync"),
    ("Amazon", "amazon_sync"),
    ("eBay", "ebay_sync"),
]


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")

    if text.count(ANCHOR) != 1:
        print(f"REFUSING: helper anchor matched {text.count(ANCHOR)} times, need 1")
        return 1

    lines = text.split("\n")
    hits: list[tuple[int, str]] = []
    for label, name in SYNCS:
        marker = f'logger.info("autopilot: {label} sync needs MFA'
        found = [i for i, ln in enumerate(lines) if marker in ln]
        if len(found) != 1:
            print(f"REFUSING: {label} log line matched {len(found)} times, need 1")
            return 1
        hits.append((found[0], name))

    before = hashlib.sha256(text.encode()).hexdigest()
    BACKUP.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(TARGET, BACKUP)

    for idx, name in hits:
        lines[idx] = (
            f'            logger.info("autopilot: {name} sync needs MFA - '
            f'notifying the owner queue")\n'
            f'            self._notify_owner_sync_needs_login("{name}", msg)'
        )

    new = "\n".join(lines).replace(ANCHOR, ANCHOR + HELPER, 1)

    # Assert on the CALL, never the bare phrase: this script's own HELPER docstring
    # quotes the phrase to explain what was wrong, so a substring check trips on its
    # own explanation. Third time across this session's tooling -- see L232.
    leftover = re.findall(
        r'logger\.info\([^)]*will surface in next owner check-in', new
    )
    checks = [
        ("helper defined", "def _notify_owner_sync_needs_login(" in new),
        ("five call sites", new.count("self._notify_owner_sync_needs_login(") == 5),
        ("old promise gone", not leftover),
        ("held status used", 'status="held",' in new),
        ("dedup reason", 'reason=f"sync_needs_login:{name}"' in new),
        ("nudge helper intact", "def _enqueue_owner_nudge(" in new),
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
