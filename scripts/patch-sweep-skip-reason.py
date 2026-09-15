"""A scheduled task that refuses to run must say why, once.

Measured 2026-09-15: "Lifecycle sweep complete" stopped appearing at 13:30:09 and
did not return across four restarts. The call site is definitely reached --
financial_alert_sweep (autopilot.py:6017) and activity_sync (autopilot.py:6061)
both recorded fresh timestamps on either side of `_maybe_run_lifecycle_sweep()` at
6023 -- and neither of the method's two silent swallows fired, so it must be one of
its two early `return`s:

    if not getattr(self._settings, "lifecycle_sweep_enabled", True): return
    if (now - last) < interval: return

Read from a separate process both gates are open (enabled=True, interval=120, and
the monotonic clock starts at 0.0 on a restart so the first tick must pass). So the
gates are being read differently inside the running process, and there is currently
no way to tell from outside.

This patch makes a refusal visible, once per distinct reason, and clears the reason
when the sweep runs again. It is an observability fix, not a behaviour change: the
sweep still runs exactly when it did before.
"""

from __future__ import annotations

import pathlib
import sys

AUTO = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "autopilot.py"

ANCHOR = '''    def _maybe_run_lifecycle_sweep(self) -> None:
        """D013: Run goal lifecycle sweep on configurable interval."""
        if not getattr(self._settings, "lifecycle_sweep_enabled", True):
            return

        interval = getattr(self._settings, "lifecycle_sweep_interval_sec", 120)
        now = time.monotonic()
        last = getattr(self, "_last_lifecycle_sweep_at", 0.0)
        if (now - last) < interval:
            return
        self._last_lifecycle_sweep_at = now
'''

REPLACE = '''    def _log_sweep_skip(self, reason: str) -> None:
        """Say why the lifecycle sweep is not running -- once per distinct reason.

        Measured 2026-09-15: the sweep's own log line stopped at 13:30:09 and did not
        return across four restarts, while the loop kept running and calling this
        method (financial_alert_sweep and activity_sync, which sit on either side of
        the call, both recorded fresh timestamps). From outside there was no way to
        distinguish "never called" from "called and refused", and a lifecycle sweep
        that is quietly off disables stale-claim release, retry scheduling, blocked-step
        reopen, goal rollup, stuck detection, draft and approval expiry, stale-task
        close, and the owner-message shelf life. So a refusal is stated, not implied.
        """
        if getattr(self, "_sweep_skip_reason", None) == reason:
            return
        self._sweep_skip_reason = reason
        logger.warning("Lifecycle sweep not running: %s", reason)

    def _maybe_run_lifecycle_sweep(self) -> None:
        """D013: Run goal lifecycle sweep on configurable interval."""
        if not getattr(self._settings, "lifecycle_sweep_enabled", True):
            self._log_sweep_skip(
                "lifecycle_sweep_enabled is %r on the controller's settings object"
                % getattr(self._settings, "lifecycle_sweep_enabled", "<absent>")
            )
            return

        interval = getattr(self._settings, "lifecycle_sweep_interval_sec", 120)
        now = time.monotonic()
        last = getattr(self, "_last_lifecycle_sweep_at", 0.0)
        if (now - last) < interval:
            # Normal on most ticks (this runs every 30 s against a 120 s interval), so
            # only a *change* of reason is ever logged.
            self._log_sweep_skip(
                "waiting for the interval (%.0fs of %.0fs elapsed, interval=%r)"
                % (now - last, interval, interval)
            )
            return
        self._last_lifecycle_sweep_at = now
        self._sweep_skip_reason = None
'''

EDITS = [(ANCHOR, REPLACE, "lifecycle sweep: state the reason for a refusal")]


def main() -> int:
    text = AUTO.read_text(encoding="utf-8")
    for old, new, label in EDITS:
        count = text.count(old)
        if count != 1:
            print(f"REFUSE {label}: anchor count {count} (expected 1)")
            return 2
        if new in text:
            print(f"REFUSE {label}: already applied")
            return 2
        text = text.replace(old, new, 1)
        print(f"planned  {label}")
    AUTO.write_text(text, encoding="utf-8")
    print(f"WROTE {AUTO}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
