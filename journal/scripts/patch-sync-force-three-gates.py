"""A manual sync run has three gates to clear, not one.

Measured 2026-09-15, immediately after adding the dispatch: `POST
/autopilot/subsystems/ebay_sync/run-once` returned `{"ran": false, "status": "ok", "detail":
"eBay sync complete -- 0 new transactions..."}` -- the detail of the *previous* run, because
the sync method has three guards and only the first had been cleared:

  1. `self._ebay_sync_run_date == today`            (in-memory, reset on restart)
  2. `subsystem_health["ebay_sync"]["last_ran_at"][:10] == today`  (persisted, restart-safe)
  3. `now_minutes < sync_minutes`                   (the scheduled hour, e.g. 04:15)

The persisted one is why the force did nothing; the third would block any manual run before
the configured hour. All three are now neutralised for the duration of the call and restored
when it did not run, so a manual attempt cannot move the daily schedule. The enable flag and
the failure breaker are still respected, and the endpoint says which one refused.
"""

from __future__ import annotations

import pathlib
import sys

AUTO = pathlib.Path.home() / "personal-secretary-mvp" / "app" / "autopilot.py"

ANCHOR = '''        before_guard = getattr(self, guard_attr, None)
        before_ran = (self._subsystem_health.get(name) or {}).get("last_ran_at")
        setattr(self, guard_attr, None)
        try:
            getattr(self, method_name)()
        finally:
            if getattr(self, guard_attr, None) is None:
                # It did not run (disabled path inside the method, or nothing to do): leave
                # the day guard exactly as it was so a manual attempt cannot extend the day.
                setattr(self, guard_attr, before_guard)'''

REPLACE = '''        before_guard = getattr(self, guard_attr, None)
        entry_before = dict(self._subsystem_health.get(name) or {})
        before_ran = entry_before.get("last_ran_at")
        # The sync methods have three gates, and a manual run must clear all three or it
        # silently does nothing (measured: clearing only the first returned {"ran": false}
        # while quoting the previous run's detail): the in-memory day guard, the persisted
        # `last_ran_at` the restart-safe guard reads, and the scheduled hour. All are
        # restored below when the run did not happen, so the daily schedule cannot move.
        time_flag = "%s_time" % name[: -len("_sync")]
        before_time = getattr(self._settings, time_flag, None)
        setattr(self, guard_attr, None)
        self._subsystem_health.setdefault(name, {})["last_ran_at"] = None
        if before_time is not None:
            try:
                setattr(self._settings, time_flag, "00:00")
            except Exception:  # noqa: BLE001 - a frozen setting is not a failure to run now
                before_time = None
        try:
            getattr(self, method_name)()
        finally:
            if getattr(self, guard_attr, None) is None:
                setattr(self, guard_attr, before_guard)
            if not (self._subsystem_health.get(name) or {}).get("last_ran_at"):
                self._subsystem_health[name] = entry_before
            if before_time is not None:
                try:
                    setattr(self._settings, time_flag, before_time)
                except Exception:  # noqa: BLE001
                    pass'''


def main() -> int:
    text = AUTO.read_text(encoding="utf-8")
    if text.count(ANCHOR) != 1:
        print(f"REFUSE: anchor count {text.count(ANCHOR)} (expected 1)")
        return 2
    if REPLACE in text:
        print("REFUSE: already applied")
        return 2
    AUTO.write_text(text.replace(ANCHOR, REPLACE, 1), encoding="utf-8")
    print(f"WROTE {AUTO}")
    print("PATCH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
