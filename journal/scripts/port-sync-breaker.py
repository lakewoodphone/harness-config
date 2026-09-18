"""Port the sync-breaker cooldown into the authority's live autopilot.py.

Gated: every anchor must match EXACTLY ONCE or nothing is written.

The defect: the breaker blocks a sync at N consecutive failures and was documented
as clearing only on a successful run or a manual reset -- but the check runs before
the sync, and subsystem_health is persisted, so a tripped sync could never clear.
boa_sync sat at 114 failures, amazon_sync and ebay_sync at 42, spending_report at
38, with the bank feed and spending report stale behind them.

Three edits: the constant, the corrected docstring, and the cooldown check.
"""

from __future__ import annotations

import hashlib
import shutil
import sys
from pathlib import Path

TARGET = Path("app/autopilot.py")
BACKUP = Path(".runtime/deploy-backups/handport-sync-breaker.py.pre")

DEF_OLD = '''    def _finance_sync_blocked_by_breaker(self, name: str) -> bool:
        """Return True when a data-source sync should skip this run.
'''

DEF_NEW = '''    # How long a tripped sync breaker waits before it is allowed one probe retry.
    # A breaker that can only be cleared by a successful run -- while blocking the
    # run -- never clears, and subsystem_health is persisted, so it survives every
    # restart too. Measured 2026-09-14: boa_sync sat at 114 consecutive failures,
    # amazon_sync and ebay_sync at 42 each and spending_report at 38, for days, with
    # the bank feed and the spending report stale behind them.
    _SYNC_BREAKER_COOLDOWN_MIN = 360

    def _finance_sync_blocked_by_breaker(self, name: str) -> bool:
        """Return True when a data-source sync should skip this run.
'''

DOC_OLD = '''        silently retried forever. Once triggered, it stays paused until a successful
        run (clears the counter) or an explicit manual reset.
'''

DOC_NEW = '''        silently retried forever.

        A tripped breaker is a **pause with a cooldown, not a permanent block**
        (fixed 2026-09-14). It used to say "stays paused until a successful run
        clears the counter or an explicit manual reset" -- but this check runs
        *before* the sync, so a tripped sync never ran, never succeeded and never
        cleared, and nothing but a human resetting state could un-wedge it. After
        ``_SYNC_BREAKER_COOLDOWN_MIN`` the sync gets one probe attempt: success
        clears the counter, failure re-trips the breaker and restarts the cooldown.
'''

COOLDOWN_OLD = '''        # Surface the trip exactly once (first run past the threshold).
'''

COOLDOWN_NEW = '''        # Cooldown: allow a single probe attempt once the last attempt is old
        # enough. This is the only automatic way out of the tripped state, so a
        # missing or unreadable timestamp must ALSO allow the probe -- an entry
        # with no evidence of a recent attempt is not a reason to block forever,
        # which is the same permanent-lock defect in a different disguise.
        age_min = None
        last_ran = entry.get("last_ran_at")
        if last_ran:
            try:
                stamp = str(last_ran).replace("Z", "+00:00")
                age_min = (
                    datetime.now(timezone.utc) - datetime.fromisoformat(stamp)
                ).total_seconds() / 60.0
            except Exception:  # noqa: BLE001 - unreadable means unknown, not recent
                age_min = None
        if age_min is None or age_min >= self._SYNC_BREAKER_COOLDOWN_MIN:
            logger.info(
                "sync breaker for %s: %d consecutive failures, last attempt %s "
                "- allowing one probe attempt",
                name,
                consec,
                "unknown" if age_min is None else "%.0f min ago" % age_min,
            )
            return False

        # Surface the trip exactly once (first run past the threshold).
'''

EDITS = [
    ("cooldown-constant", DEF_OLD, DEF_NEW),
    ("corrected-docstring", DOC_OLD, DOC_NEW),
    ("cooldown-check", COOLDOWN_OLD, COOLDOWN_NEW),
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
        ("constant present", "_SYNC_BREAKER_COOLDOWN_MIN = 360" in new),
        ("cooldown returns False", "return False\n\n        # Surface the trip" in new),
        ("age parsed", "datetime.fromisoformat(stamp)" in new),
        ("owner nudge kept", "self._enqueue_owner_nudge(name" in new),
        ("threshold check kept", "if consec < self._SYNC_BREAKER_THRESHOLD:" in new),
        ("cooldown documented", "pause with a cooldown, not a permanent block" in new),
        ("old claim not asserted", "it stays paused until a successful" not in new),
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
